fn main() {
    println!("cargo:rerun-if-changed=native/permissions.m");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        let identity: serde_json::Value = serde_json::from_str(include_str!("../../packaging/identity.json")).unwrap();
        let trust: serde_json::Value = serde_json::from_str(include_str!("../../packaging/update-trust.json")).unwrap();
        let team = identity["macos"]["team_id"].as_str().expect("Mac signing team");
        let fingerprint = identity["macos"]["signing_fingerprint"]
            .as_str()
            .expect("Mac signing certificate");
        assert!(team.len() == 10 && team.bytes().all(|b| b.is_ascii_alphanumeric()));
        assert!(fingerprint.len() == 40 && fingerprint.bytes().all(|b| b.is_ascii_hexdigit()));
        cc::Build::new()
            .file("native/permissions.m")
            .file("native/local-update.m")
            .define("OINK_SIGNING_TEAM", Some(format!("\"{team}\"").as_str()))
            .define(
                "OINK_DEVELOPMENT_FINGERPRINT",
                Some(format!("\"{fingerprint}\"").as_str()),
            )
            .define(
                "OINK_ALLOW_DEVELOPMENT_UPDATES",
                if trust["mac"]["allow_development_updates"] == true {
                    "1"
                } else {
                    "0"
                },
            )
            .flag("-fobjc-arc")
            .flag("-fblocks")
            .flag("-mmacosx-version-min=14.2")
            .warnings(true)
            .compile("oink_permissions");
        println!("cargo:rerun-if-changed=native/local-update.m");
        println!("cargo:rerun-if-changed=../../packaging/identity.json");
        println!("cargo:rerun-if-changed=../../packaging/update-trust.json");
        println!("cargo:rustc-link-lib=framework=Security");
        println!("cargo:rustc-link-lib=framework=Network");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }
    println!("cargo:rerun-if-env-changed=OINK_RELEASE_BUILD");
    println!("cargo:rerun-if-env-changed=RELEASE_BUILD");
    // Release controller exports RELEASE_BUILD for every build/package job.
    // The explicit prefixed variable is also supported for isolated build proofs.
    let build = std::env::var("OINK_RELEASE_BUILD")
        .or_else(|_| std::env::var("RELEASE_BUILD"))
        .unwrap_or_else(|_| "0".into());
    let numeric: u64 = build.parse().expect("OINK_RELEASE_BUILD must be a numeric build");
    assert!(numeric < (1u64 << 31), "release build exceeds MSI range");
    println!("cargo:rustc-env=OINK_RELEASE_BUILD={numeric}");
    println!("cargo:rerun-if-env-changed=OINK_RELEASE_VERSION");
    let version = std::env::var("OINK_RELEASE_VERSION")
        .unwrap_or_else(|_| std::env::var("CARGO_PKG_VERSION").expect("package version"));
    println!("cargo:rustc-env=OINK_RELEASE_VERSION={version}");
    println!("cargo:rerun-if-env-changed=OINK_SOURCE_TREE_SHA256");
    let tree = std::env::var("OINK_SOURCE_TREE_SHA256").unwrap_or_else(|_| "unrecorded".into());
    assert!(
        tree == "unrecorded"
            || (tree.len() == 64 && tree.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))),
        "OINK_SOURCE_TREE_SHA256 must be 64 lowercase hexadecimal characters"
    );
    println!("cargo:rustc-env=OINK_DIAGNOSTIC_SOURCE_TREE_SHA256={tree}");
}
