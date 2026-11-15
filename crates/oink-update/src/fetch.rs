//! Catalog lookup across the configured sources and HTTPS transfers, shared by
//! the Windows service and the macOS backend.
use crate::Error;

/// Tries each source in order and returns the first catalog that verifies.
/// Any failure moves on to the next source. When all fail, a verification
/// failure is reported in preference to a network failure: it says more.
pub fn first_verified<T>(
    sources: &[String],
    path: &str,
    mut get: impl FnMut(&str) -> Result<Vec<u8>, Error>,
    mut verify: impl FnMut(&[u8]) -> Result<T, Error>,
) -> Result<T, Error> {
    let mut failure = None;
    for source in sources {
        match get(&source_url(source, path)).and_then(|bytes| verify(&bytes)) {
            Ok(value) => return Ok(value),
            Err(error) => {
                if failure.is_none_or(|first| first == Error::Network) {
                    failure = Some(error);
                }
            }
        }
    }
    Err(failure.unwrap_or(Error::NotConfigured))
}

/// This fork publishes update snapshots as flat GitHub Release assets.
const RELEASE_FEED: &str = "https://github.com/Natsuneko3/oink/releases/download/update-feed";
fn safe_segment(segment: &str) -> bool {
    !segment.is_empty()
        && !matches!(segment, "." | "..")
        && segment
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
}
fn source_url(source: &str, path: &str) -> String {
    if source == RELEASE_FEED && path.split('/').all(safe_segment) {
        format!("{source}/{}", path.replace('/', "-"))
    } else {
        format!("{source}/{path}")
    }
}
#[cfg(any(feature = "http", test))]
fn allows_redirect(original: &str, target: &str, hop: usize, package: bool) -> bool {
    if !package {
        let asset = original
            .strip_prefix(RELEASE_FEED)
            .and_then(|suffix| suffix.strip_prefix('/'));
        let release_catalog = asset.is_some_and(|asset| {
            safe_segment(asset)
                && (asset.starts_with("windows-v1-")
                    || asset.starts_with("windows-v2-")
                    || asset.starts_with("mac-v2-"))
                && asset.ends_with("-manifest.json")
        });
        let github_cdn = url::Url::parse(target).is_ok_and(|target| {
            matches!(
                target.host_str(),
                Some("release-assets.githubusercontent.com" | "objects.githubusercontent.com")
            ) && target.port().is_none()
        });
        if !release_catalog || !github_cdn {
            return false;
        }
    }
    crate::feed::validate_redirect(target, hop).is_ok()
}

/// GET catalogs without redirects, except the fork's GitHub Release manifests
/// may redirect to GitHub's asset CDN. Packages may follow HTTPS redirects to
/// their CDN. `progress` receives (received, expected) as bytes arrive.
#[cfg(feature = "http")]
pub fn get(url: &str, limit: u64, package: bool, progress: &mut dyn FnMut(u64, u64)) -> Result<Vec<u8>, Error> {
    get_until(url, limit, package, &mut |received, expected| {
        progress(received, expected);
        true
    })
}
/// As [`get`], but the transfer is abandoned (as `Error::Network`) as soon as
/// `progress` returns false.
#[cfg(feature = "http")]
pub fn get_until(
    url: &str,
    limit: u64,
    package: bool,
    progress: &mut dyn FnMut(u64, u64) -> bool,
) -> Result<Vec<u8>, Error> {
    use std::{io::Read, time::Duration};
    let original = url.to_owned();
    let policy = reqwest::redirect::Policy::custom(move |attempt| {
        if allows_redirect(&original, attempt.url().as_str(), attempt.previous().len(), package) {
            attempt.follow()
        } else {
            attempt.stop()
        }
    });
    // The client timeout bounds connecting and each read, not the whole body,
    // so a slow but live download is never cut off.
    let client = reqwest::blocking::Client::builder()
        .https_only(!cfg!(feature = "test-feed"))
        .redirect(policy)
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(60))
        .user_agent("Oink-updater/2")
        .build()
        .map_err(|_| Error::Network)?;
    let response = client.get(url).send().map_err(|_| Error::Network)?;
    if response.status() != reqwest::StatusCode::OK || response.content_length().is_some_and(|n| n > limit) {
        return Err(Error::Network);
    }
    let expected = response.content_length().unwrap_or(limit);
    let mut body = response.take(limit + 1);
    let mut bytes = Vec::with_capacity(expected.min(limit) as usize);
    let mut chunk = vec![0; 256 * 1024];
    loop {
        let read = body.read(&mut chunk).map_err(|_| Error::Network)?;
        if read == 0 {
            break;
        }
        bytes.extend_from_slice(&chunk[..read]);
        if bytes.len() as u64 > limit {
            return Err(Error::Limit);
        }
        if !progress(bytes.len() as u64, expected) {
            return Err(Error::Network);
        }
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sources() -> Vec<String> {
        vec![
            "https://a.example".into(),
            "https://b.example".into(),
            "https://c.example".into(),
        ]
    }
    #[test]
    fn release_sources_use_flat_catalog_asset_names() {
        let sources = vec!["https://github.com/Natsuneko3/oink/releases/download/update-feed".into()];
        for (path, expected) in [
            (
                "windows/v2/win-2026-01/x64/stable/manifest.json",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/windows-v2-win-2026-01-x64-stable-manifest.json",
            ),
            (
                "mac/v2/mac-2026-01/arm64/beta/manifest.json",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/mac-v2-mac-2026-01-arm64-beta-manifest.json",
            ),
        ] {
            let result = first_verified(
                &sources,
                path,
                |url| {
                    if url == expected {
                        Ok(b"signed".to_vec())
                    } else {
                        Err(Error::Network)
                    }
                },
                |bytes| {
                    if bytes == b"signed" {
                        Ok(())
                    } else {
                        Err(Error::Signature)
                    }
                },
            );
            assert_eq!(result, Ok(()), "{path}");
        }
    }
    #[test]
    fn ordinary_sources_keep_hierarchical_paths_including_prefixes() {
        for source in [
            "https://updates.oink.hachiwii.com",
            "https://mirror.example/oink",
            "https://github.com/Natsuneko3/oink/releases/download/other-feed",
            "https://github.com/Natsuneko3/oink-other/releases/download/update-feed",
        ] {
            let mut asked = String::new();
            let result = first_verified(
                &[source.into()],
                "mac/v2/mac-2026-01/arm64/stable/manifest.json",
                |url| {
                    asked = url.into();
                    Ok(vec![])
                },
                |_| Ok(()),
            );
            assert_eq!(result, Ok(()));
            assert_eq!(asked, format!("{source}/mac/v2/mac-2026-01/arm64/stable/manifest.json"));
        }
    }
    #[test]
    fn only_the_release_feed_catalogs_follow_github_cdn_redirects() {
        let catalog = "https://github.com/Natsuneko3/oink/releases/download/update-feed/windows-v2-win-2026-01-x64-stable-manifest.json";
        for cdn in [
            "https://release-assets.githubusercontent.com/github-production-release-asset/123/asset?signature=abc",
            "https://objects.githubusercontent.com/github-production-release-asset/123/asset",
        ] {
            assert!(allows_redirect(catalog, cdn, 1, false), "{cdn}");
            assert!(!allows_redirect(catalog, cdn, 6, false));
            for other_catalog in [
                "https://updates.oink.hachiwii.com/windows/v2/win-2026-01/x64/stable/manifest.json",
                "https://github.com/Natsuneko3/oink-other/releases/download/update-feed/windows-v2-win-2026-01-x64-stable-manifest.json",
                "https://github.com/Natsuneko3/oink/releases/download/other-feed/windows-v2-win-2026-01-x64-stable-manifest.json",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/windows/v2/manifest.json",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/windows-v2-win-2026-01-x64-stable-manifest.json?redirect=1",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/windows-v2-win-2026-01-x64-stable-manifest.json#fragment",
                "https://github.com/Natsuneko3/oink/releases/download/update-feed/Oink.msi",
            ] {
                assert!(!allows_redirect(other_catalog, cdn, 1, false), "{other_catalog}");
            }
        }
        for target in [
            "http://release-assets.githubusercontent.com/asset",
            "https://user@release-assets.githubusercontent.com/asset",
            "https://release-assets.githubusercontent.com:9443/asset",
            "https://release-assets.githubusercontent.com.evil.test/asset",
            "https://unrelated.example/asset",
        ] {
            assert!(!allows_redirect(catalog, target, 1, false), "{target}");
        }
        // Package transfers retain their existing signed-byte HTTPS CDN policy.
        assert!(allows_redirect(
            "https://github.com/Natsuneko3/oink/releases/download/v1/Oink.msi",
            "https://cdn.example/package",
            1,
            true
        ));
    }
    #[test]
    fn the_first_source_that_verifies_wins() {
        let mut asked = vec![];
        let result = first_verified(
            &sources(),
            "windows/v2/x/manifest.json",
            |url| {
                asked.push(url.to_owned());
                match url {
                    "https://a.example/windows/v2/x/manifest.json" => Err(Error::Network),
                    "https://b.example/windows/v2/x/manifest.json" => Ok(b"stale".to_vec()),
                    _ => Ok(b"good".to_vec()),
                }
            },
            |bytes| if bytes == b"good" { Ok(7) } else { Err(Error::Replay) },
        );
        assert_eq!(result, Ok(7));
        assert_eq!(asked.len(), 3);
    }
    #[test]
    fn a_verification_failure_outranks_network_failures() {
        let fail = |error| {
            first_verified(
                &sources(),
                "p",
                |url| {
                    if url.starts_with("https://b") {
                        Ok(vec![])
                    } else {
                        Err(Error::Network)
                    }
                },
                |_| Err::<(), _>(error),
            )
        };
        assert_eq!(fail(Error::Signature), Err(Error::Signature));
        assert_eq!(
            first_verified(&sources(), "p", |_| Err(Error::Network), |_| Ok(())),
            Err(Error::Network)
        );
        assert_eq!(
            first_verified(&[], "p", |_| Ok(vec![]), |_| Ok(())),
            Err(Error::NotConfigured)
        );
    }
}
