import SwiftUI

// MARK: - Card container

/// A rounded surface with a hairline border — the base building block for rows,
/// panels, and message bubbles.
struct Card<Content: View>: View {
    var padding: CGFloat = 16
    var fill: Color = Theme.surface
    var radius: CGFloat = Theme.radius
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(fill, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(Theme.hairline, lineWidth: 1)
            )
    }
}

// MARK: - Primary button

/// Full-width gradient action button with a press animation.
struct PrimaryButton: View {
    let title: String
    var systemImage: String? = nil
    var loading: Bool = false
    var enabled: Bool = true
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if loading {
                    ProgressView().tint(.white).scaleEffect(0.85)
                } else if let systemImage {
                    Image(systemName: systemImage)
                }
                Text(title).fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .foregroundStyle(.white)
            .background(Theme.accentGradient, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)
            )
            .shadow(color: Theme.accent.opacity(0.35), radius: 18, y: 8)
            .opacity(enabled && !loading ? 1 : 0.55)
        }
        .buttonStyle(PressStyle())
        .disabled(!enabled || loading)
    }
}

/// Subtle secondary button on a surface.
struct GhostButton: View {
    let title: String
    var systemImage: String? = nil
    var tint: Color = Theme.text
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                if let systemImage { Image(systemName: systemImage) }
                Text(title).fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .foregroundStyle(tint)
            .background(Theme.surfaceHi, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Theme.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(PressStyle())
    }
}

/// Squishes slightly while pressed — makes taps feel tactile.
struct PressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.28, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

// MARK: - Text field

/// Dark, borderless-looking text field on a surface with an optional icon.
struct FieldRow: View {
    var icon: String? = nil
    let placeholder: String
    @Binding var text: String
    var keyboard: UIKeyboardType = .default
    var mono: Bool = false

    var body: some View {
        HStack(spacing: 10) {
            if let icon {
                Image(systemName: icon)
                    .foregroundStyle(Theme.textFaint)
                    .frame(width: 18)
            }
            TextField("", text: $text, prompt: Text(placeholder).foregroundColor(Theme.textFaint))
                .foregroundStyle(Theme.text)
                .font(mono ? .system(.body, design: .monospaced) : .body)
                .keyboardType(keyboard)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(Theme.surfaceHi, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Theme.hairline, lineWidth: 1)
        )
    }
}

// MARK: - Status pill

struct StatusPill: View {
    let text: String
    var color: Color = Theme.accent

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text(text.uppercased())
                .font(.system(size: 10, weight: .bold))
                .tracking(0.5)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 9)
        .padding(.vertical, 4)
        .background(color.opacity(0.12), in: Capsule())
    }
}

// MARK: - Section header

struct SectionHeader: View {
    let title: String
    var trailing: String? = nil

    var body: some View {
        HStack {
            Text(title.uppercased())
                .font(.system(size: 12, weight: .bold))
                .tracking(1.2)
                .foregroundStyle(Theme.textFaint)
            Spacer()
            if let trailing {
                Text(trailing)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Theme.textFaint)
            }
        }
    }
}

// MARK: - Empty state

struct EmptyState: View {
    let icon: String
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Theme.textFaint)
            Text(title)
                .font(.headline)
                .foregroundStyle(Theme.textDim)
            if let subtitle {
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(Theme.textFaint)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 48)
        .padding(.horizontal, 24)
    }
}

// MARK: - Background

/// App-wide backdrop: deep base with two soft accent blooms in the corners.
struct AppBackground: View {
    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            Circle()
                .fill(Theme.accent.opacity(0.16))
                .frame(width: 320, height: 320)
                .blur(radius: 120)
                .offset(x: -140, y: -260)
            Circle()
                .fill(Theme.cyan.opacity(0.10))
                .frame(width: 300, height: 300)
                .blur(radius: 130)
                .offset(x: 160, y: 320)
        }
        .ignoresSafeArea()
    }
}

// MARK: - Helpers

extension View {
    /// Hide the keyboard from anywhere.
    func dismissKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}
