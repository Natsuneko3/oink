//! Physical-source policy. Native capture modes describe cursor ownership, never
//! group focus: local mouse use can reveal a cursor while the group is elsewhere.
use super::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceInput {
    Motion,
    RawMotion,
    Button,
    Keyboard,
    Scroll,
    Gesture,
    Contacts,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceDestination {
    Local,
    Forwarded,
    Consumed,
}
/// Content-free evidence of the actual source routing decision, including transformed
/// local injection and consumed hotkeys/held tails. Contains no key/button identities.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceDecision {
    pub mouse_mode: InputMode,
    pub keyboard_mode: InputMode,
    pub input: SourceInput,
    pub destination: SourceDestination,
    pub swallowed: bool,
}
impl Router {
    pub fn game_input_local(&self) -> bool {
        let game = self.game_mode();
        game.active && game.local_input
    }
    fn effective_input_mode(&self, mode: InputMode) -> InputMode {
        if mode == InputMode::Shared && self.game_input_local() {
            InputMode::Local
        } else {
            mode
        }
    }
    pub fn mouse_local(&self) -> bool {
        self.effective_input_mode(self.cfg.settings.mouse_mode) == InputMode::Local
    }
    pub fn mouse_disabled(&self) -> bool {
        self.cfg.settings.mouse_mode == InputMode::Disabled
    }
    pub fn keyboard_local(&self) -> bool {
        self.effective_input_mode(self.cfg.settings.keyboard_mode) == InputMode::Local
    }
    /// A parked cursor has no usable event position. Restore from the remembered
    /// local position, applying the first physical motion there instead of letting
    /// a stale native park position move the cursor across the screen.
    pub(super) fn reveal_local_mouse(&mut self, ev: &CapturedEvent) -> bool {
        if !self.local_mouse_hidden
            || !self.mouse_local()
            || !ev.physical
            || self.fully_paused
            || !self.capture_available
        {
            return false;
        }
        match ev.event {
            // Raw motion is observational and precedes normal motion on macOS.
            // Let the normal event restore with its accelerated delta once.
            InputEvent::Key { .. } | InputEvent::RawPointerDelta { .. } => return false,
            InputEvent::PointerDelta { dx: 0., dy: 0. } => {
                return false;
            }
            _ => {}
        }
        self.local_mouse_hidden = false;
        if let Some(mut p) = self.local_cursor.clone().or_else(|| self.display_center()) {
            if let InputEvent::PointerDelta { dx, dy } = ev.event
                && let Some(display) = self.displays.iter().find(|d| d.key == p.screen.display)
            {
                p.local = display.bounds.clamp(Point::new(p.local.x + dx, p.local.y + dy));
            }
            self.out.push(Output::RestoreLocal { at: p.local });
            self.local_cursor = Some(p);
        } else {
            self.out.push(Output::SetMode(CaptureMode::Local));
        }
        true
    }

    pub(super) fn replay_local_mouse_wake(&mut self, ev: &CapturedEvent) -> Disposition {
        // The native event was captured while parked. Motion is accounted for by
        // RestoreLocal; a button/wheel/gesture must execute after that restore,
        // rather than be swallowed by the old native mode or hit its park point.
        let event = match ev.event {
            InputEvent::Button { button, pressed: true } => {
                self.buttons.insert(button, Target::LocalInjected);
                self.target_button(self.me(), button, true);
                return Disposition::Swallow;
            }
            InputEvent::Button { button, pressed: false } => InjectEvent::Button { button, pressed: false },
            InputEvent::Scroll {
                mut dx,
                mut dy,
                unit,
                phase,
                ..
            } => {
                if self.local_rewrite.take() == Some(oink_foundation::input::LocalRewrite::ReverseWheel) {
                    dx = -dx;
                    dy = -dy;
                }
                InjectEvent::Scroll { dx, dy, unit, phase }
            }
            InputEvent::Gesture(g) => InjectEvent::Gesture(g),
            _ => return Disposition::Pass,
        };
        self.out.push(Output::Inject(event));
        Disposition::Swallow
    }
    pub(super) fn mouse_target(&self) -> Target {
        if self.mouse_local() {
            Target::Local
        } else {
            self.current_target()
        }
    }
    pub(super) fn source_is_local(&self, event: &InputEvent) -> bool {
        match event {
            InputEvent::Key { .. } => self.keyboard_local(),
            _ => self.mouse_local(),
        }
    }
    pub(super) fn source_decision(&self, event: &InputEvent, disposition: Disposition, start: usize) {
        let Some(sink) = self.diagnostics.as_ref().filter(|s| s.enabled()) else {
            return;
        };
        let input = match event {
            InputEvent::PointerDelta { .. } => SourceInput::Motion,
            InputEvent::RawPointerDelta { .. } => SourceInput::RawMotion,
            InputEvent::Button { .. } => SourceInput::Button,
            InputEvent::Key { .. } => SourceInput::Keyboard,
            InputEvent::Scroll { .. } => SourceInput::Scroll,
            InputEvent::Gesture(_) => SourceInput::Gesture,
            InputEvent::TouchpadSample(_) | InputEvent::TouchpadBoundary => SourceInput::Contacts,
        };
        let forwarded = self.out[start..].iter().any(|o| {
            matches!(
                o,
                Output::Send {
                    msg: Message::Input(_) | Message::TimedInput { .. },
                    ..
                }
            )
        });
        let injected = self.local_rewrite.is_some()
            || self.out[start..].iter().any(|o| match (event, o) {
                (InputEvent::Key { code, .. }, Output::Inject(InjectEvent::Key { code: mapped, .. })) => {
                    *mapped != KeyCode::MENU_MASK || *code == KeyCode::MENU_MASK
                }
                (InputEvent::Button { .. }, Output::Inject(InjectEvent::Button { .. }))
                | (InputEvent::Scroll { .. }, Output::Inject(InjectEvent::Scroll { .. }))
                | (InputEvent::Gesture(_), Output::Inject(InjectEvent::Gesture(_))) => true,
                _ => false,
            });
        sink.source_decision(SourceDecision {
            mouse_mode: self.cfg.settings.mouse_mode,
            keyboard_mode: self.cfg.settings.keyboard_mode,
            input,
            destination: if forwarded {
                SourceDestination::Forwarded
            } else if disposition == Disposition::Pass || injected {
                SourceDestination::Local
            } else {
                SourceDestination::Consumed
            },
            swallowed: disposition == Disposition::Swallow,
        });
    }
    pub(super) fn apply_source_modes(&mut self, mouse: InputMode, keyboard: InputMode) {
        if keyboard != self.cfg.settings.keyboard_mode {
            let was_disabled = self.keyboard_disabled();
            if self.effective_input_mode(keyboard) != self.effective_input_mode(self.cfg.settings.keyboard_mode) {
                self.retire_source_keyboard();
            }
            self.cfg.settings.keyboard_mode = keyboard;
            if was_disabled || keyboard == InputMode::Disabled {
                self.keyboard_mode_changed(keyboard == InputMode::Disabled);
            }
        }
        if self.effective_input_mode(mouse) != self.effective_input_mode(self.cfg.settings.mouse_mode) {
            self.apply_mouse_mode(self.effective_input_mode(mouse));
        }
    }

    /// Temporary game policy never changes the saved modes or the group focus,
    /// which also drives clipboard and other independent sharing features.
    pub(super) fn apply_game_input_mode(&mut self, active: bool) {
        if self.cfg.settings.keyboard_mode == InputMode::Shared
            && (self.holder != self.me()
                || self
                    .keys
                    .values()
                    .flatten()
                    .any(|target| matches!(target, Target::Remote(_))))
        {
            self.retire_source_keyboard();
        }
        if self.cfg.settings.mouse_mode == InputMode::Shared
            && (self.holder != self.me()
                || self.local_mouse_hidden
                || self.buttons.values().any(|target| matches!(target, Target::Remote(_))))
        {
            self.apply_mouse_mode(if active { InputMode::Local } else { InputMode::Shared });
        }
        if active {
            self.cancel_system_clip_motion();
            self.gap_cancel();
            self.local_click_cancel();
            self.retire_received_multifinger();
            let origins: Vec<_> = self.held.keys().copied().filter(|d| *d != self.me()).collect();
            for origin in origins {
                self.release_origin(origin);
            }
            let forwarded: Vec<_> = self.forwarded.keys().copied().collect();
            for (origin, item) in forwarded {
                self.release_press(origin, item);
            }
            self.scroll_fwd.clear();
            self.gesture_fwd.clear();
        }
    }

    fn apply_mouse_mode(&mut self, mouse: InputMode) {
        self.keyboard.cancel_injected_release_hold();
        self.local_click_cancel_own();
        self.out
            .push(Output::Status(StatusEvent::MouseDisabled(mouse == InputMode::Disabled)));
        if mouse != InputMode::Disabled {
            self.local_mouse_hidden = false;
        }
        // End only drags controlled by this physical source. A different
        // source's drag hosted on this device remains independent.
        self.dnd_retire_physical_mouse();
        self.cancel_source_contacts();
        let buttons: Vec<_> = self.buttons.drain().collect();
        for (button, target) in buttons {
            if self.release_local_button(button, target) && !self.button_refs.contains_key(&button) {
                self.out
                    .push(Output::Inject(InjectEvent::Button { button, pressed: false }));
            }
            self.buttons.insert(button, Target::Dropped);
        }
        self.cancel_source_scroll();
        // A phased gesture must not become a new gesture on another target.
        self.cancel_local_gesture();
        if (self.holder != self.me() || self.gap.is_some()) && !self.fully_paused {
            if mouse == InputMode::Local {
                // The group pointer has no position on this machine. Restore
                // the last local position, rather than its hidden park point,
                // so the user's first local motion starts where they left it.
                if let Some(p) = self
                    .local_cursor
                    .as_ref()
                    .or(self.exit_point.as_ref())
                    .cloned()
                    .or_else(|| self.display_center())
                {
                    self.out.push(Output::RestoreLocal { at: p.local });
                } else {
                    self.out.push(Output::SetMode(CaptureMode::Local));
                }
            } else if mouse == InputMode::Shared {
                self.exit_point = self.local_cursor.clone();
                self.out.push(Output::SetMode(CaptureMode::Remote {
                    park: self.park_point(),
                }));
            }
        }
    }
    pub(super) fn cancel_local_gesture(&mut self) {
        // Preserve the original target only for the cancellation. Do not send a
        // continued phase under the new mode or disturb another source's gesture.
        if let Some(target) = self.gesture_lock.take() {
            if let Some(g) = self.source_gesture.take() {
                let cancel = match g {
                    Gesture::DockSwipe { axis, progress, .. } => Gesture::DockSwipe {
                        axis,
                        phase: GesturePhase::Cancelled,
                        progress,
                        velocity: 0.,
                    },
                    Gesture::Magnify { .. } => Gesture::Magnify {
                        phase: GesturePhase::Cancelled,
                        amount: 0.,
                    },
                    Gesture::Rotate { .. } => Gesture::Rotate {
                        phase: GesturePhase::Cancelled,
                        degrees: 0.,
                    },
                    Gesture::SmartMagnify => Gesture::SmartMagnify,
                };
                match target {
                    Target::Remote(d) => self.send(
                        d,
                        Message::Input(InputMsg::Gesture {
                            source: SourceKind::Touchpad,
                            gesture: cancel,
                        }),
                    ),
                    Target::Local => self.out.push(Output::Inject(InjectEvent::Gesture(cancel))),
                    _ => {}
                }
            }
            self.gesture_lock = Some(Target::Dropped);
        }
    }
}
