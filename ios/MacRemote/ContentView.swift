import SwiftUI

/// Top-level switch between the connect screen and the authenticated app.
struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        ZStack {
            AppBackground()
            switch model.phase {
            case .connected:
                MainTabView()
                    .transition(.opacity.combined(with: .move(edge: .trailing)))
            default:
                ConnectView()
                    .transition(.opacity)
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: model.phase)
    }
}

#Preview {
    RootView().environmentObject(AppModel())
}
