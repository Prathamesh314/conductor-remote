import SwiftUI

/// Authenticated shell — three destinations behind a custom floating tab bar.
struct MainTabView: View {
    @EnvironmentObject var model: AppModel
    @State private var tab: Tab = .chats

    enum Tab: Int, CaseIterable {
        case chats, shell, settings
        var icon: String {
            switch self {
            case .chats: return "bubble.left.and.bubble.right.fill"
            case .shell: return "terminal.fill"
            case .settings: return "slider.horizontal.3"
            }
        }
        var label: String {
            switch self {
            case .chats: return "Chats"
            case .shell: return "Shell"
            case .settings: return "Settings"
            }
        }
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                switch tab {
                case .chats:    ChatsView()
                case .shell:    ShellView()
                case .settings: SettingsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            tabBar
        }
    }

    private var tabBar: some View {
        HStack(spacing: 4) {
            ForEach(Tab.allCases, id: \.rawValue) { t in
                Button {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) { tab = t }
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: t.icon)
                            .font(.system(size: 18, weight: .semibold))
                        Text(t.label)
                            .font(.system(size: 10, weight: .semibold))
                    }
                    .foregroundStyle(tab == t ? Theme.text : Theme.textFaint)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .background {
                        if tab == t {
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .fill(Theme.accent.opacity(0.18))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .strokeBorder(Theme.accent.opacity(0.35), lineWidth: 1))
                        }
                    }
                }
                .buttonStyle(PressStyle())
            }
        }
        .padding(6)
        .background(.ultraThinMaterial, in: Capsule())
        .overlay(Capsule().strokeBorder(Theme.hairlineStrong, lineWidth: 1))
        .padding(.horizontal, 40)
        .padding(.bottom, 6)
        .shadow(color: .black.opacity(0.4), radius: 20, y: 8)
    }
}
