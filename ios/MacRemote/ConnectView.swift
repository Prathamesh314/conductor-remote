import SwiftUI

/// Sign in. Enter the Mac's Tailscale IP and your email; the server emails a
/// 6-digit code, and verifying it keeps you signed in for days via saved tokens.
struct ConnectView: View {
    @EnvironmentObject var model: AppModel
    @State private var emailInput = ""
    @State private var code = ""
    @State private var forceEmail = false   // "use a different email" overrides the reconnect shortcut
    @FocusState private var focus: Field?

    enum Field { case host, email, code }

    private var busy: Bool { model.phase == .connecting }
    private var awaitingCode: Bool { model.phase == .codeSent }

    private var canSendCode: Bool {
        !model.serverHost.trimmingCharacters(in: .whitespaces).isEmpty
            && emailInput.contains("@")
    }
    private var canVerify: Bool { code.count >= 4 }

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            logo
            Spacer()

            VStack(spacing: 14) {
                FieldRow(icon: "network", placeholder: "Mac Tailscale IP  ·  100.x.x.x",
                         text: $model.serverHost, keyboard: .numbersAndPunctuation, mono: true)
                    .focused($focus, equals: .host)
                    .disabled(awaitingCode)

                if awaitingCode {
                    codeStep
                } else if model.hasSavedSession && !forceEmail {
                    reconnectStep
                } else {
                    emailStep
                }

                if !model.statusMessage.isEmpty {
                    Label(model.statusMessage, systemImage: "info.circle")
                        .font(.footnote)
                        .foregroundStyle(Theme.textDim)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .transition(.opacity)
                }
            }
            .padding(20)
            .background(Theme.surface.opacity(0.6),
                        in: RoundedRectangle(cornerRadius: Theme.radius + 4, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius + 4, style: .continuous)
                    .strokeBorder(Theme.hairline, lineWidth: 1)
            )

            Text("Runs over your Tailnet. Nothing is exposed publicly.")
                .font(.caption)
                .foregroundStyle(Theme.textFaint)
                .padding(.top, 18)

            Spacer()
        }
        .padding(.horizontal, 22)
        .animation(.easeInOut, value: model.statusMessage)
        .animation(.easeInOut, value: awaitingCode)
        .onAppear { if emailInput.isEmpty { emailInput = model.email } }
    }

    // Shortcut: a saved session is still on disk — reconnect without re-emailing.
    private var reconnectStep: some View {
        VStack(spacing: 14) {
            PrimaryButton(title: busy ? "Reconnecting…" : "Reconnect as \(model.email)",
                          systemImage: "bolt.horizontal.fill",
                          loading: busy, enabled: !busy) {
                Task { await model.resumeSession() }
            }
            .padding(.top, 4)

            Button("Use a different email") { forceEmail = true }
                .font(.footnote)
                .foregroundStyle(Theme.accent)
        }
    }

    // Step 1: enter email, request a code.
    private var emailStep: some View {
        VStack(spacing: 14) {
            FieldRow(icon: "envelope.fill", placeholder: "you@email.com",
                     text: $emailInput, keyboard: .emailAddress)
                .focused($focus, equals: .email)

            PrimaryButton(title: busy ? "Sending…" : "Email me a code",
                          systemImage: "paperplane.fill",
                          loading: busy, enabled: canSendCode) {
                dismissKeyboard()
                Task { await model.sendCode(email: emailInput) }
            }
            .padding(.top, 4)
        }
    }

    // Step 2: enter the emailed code, verify + connect.
    private var codeStep: some View {
        VStack(spacing: 14) {
            FieldRow(icon: "key.fill", placeholder: "6-digit code",
                     text: $code, keyboard: .numberPad)
                .focused($focus, equals: .code)

            PrimaryButton(title: busy ? "Verifying…" : "Verify & connect",
                          systemImage: "bolt.horizontal.fill",
                          loading: busy, enabled: canVerify) {
                dismissKeyboard()
                Task { await model.verifyCode(code) }
            }
            .padding(.top, 4)

            HStack {
                Button("Resend code") { Task { await model.sendCode(email: emailInput) } }
                Spacer()
                Button("Change email") { code = ""; model.disconnect() }
            }
            .font(.footnote)
            .foregroundStyle(Theme.accent)
            .disabled(busy)
        }
    }

    private var logo: some View {
        VStack(spacing: 18) {
            ZStack {
                RoundedRectangle(cornerRadius: 26, style: .continuous)
                    .fill(Theme.glowGradient)
                    .frame(width: 92, height: 92)
                    .shadow(color: Theme.accent.opacity(0.5), radius: 28, y: 10)
                Image(systemName: "macbook.and.iphone")
                    .font(.system(size: 40, weight: .medium))
                    .foregroundStyle(.white)
            }
            VStack(spacing: 6) {
                Text("Mac Remote")
                    .font(.system(size: 32, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.text)
                Text("Drive Conductor from your pocket")
                    .font(.subheadline)
                    .foregroundStyle(Theme.textDim)
            }
        }
    }
}
