# AI TrafficOS — Mobile Client (Phase 1: Foundation & Architecture)

This Flutter application serves as the cross-platform mobile client for **AI TrafficOS**, an intelligent municipal traffic management and adaptive signal control system.

---

## 🌟 Phase 1 Scope & Architecture

Phase 1 establishes the foundational infrastructure, design language, and honest status monitoring without mocked or fake feature data:

1. **Design System & Tokens (`lib/theme/app_tokens.dart`)**:
   - Exact token palette:
     - `ink`: `#0B1020` (scaffold background)
     - `surface`: `#131A2E`
     - `card`: `#18213A`
     - `teal`: `#00D9A8` (primary accent)
     - `amber`: `#FFB800`
     - `danger`: `#FF4D6D`
     - `success`: `#22C55E`
     - `textPrimary`: `#EAF0FF`
     - `muted`: `#8B93B0`
   - Radii: Card radius 14, Pill buttons (`Radius.circular(999)`).
   - Standard 8-point spacing scale (`space2xs` to `space3xl`).

2. **Material 3 Theming (`lib/theme/app_theme.dart`)**:
   - Dark-first default theme (`AppTheme.darkTheme`) and light variant (`AppTheme.lightTheme`).
   - Space Grotesk typography for display, headline, and title styles.
   - Inter typography for body and label styles.
   - Pill-shaped filled and outlined buttons with teal accent.

3. **Core Reusable UI Components (`lib/widgets/`)**:
   - `AppButton`: Pill-shaped primary and outlined variants with loading states.
   - `AppCard`: Radius 14 surface cards with subtle dark borders.
   - `AppBadge`: Pill badges with semantic color tints.
   - `SectionHeader`: Standardized title, subtitle, and trailing widget layouts.

4. **Models & API Wiring (`lib/models/`, `lib/services/`)**:
   - `HealthStatus`: Type-safe model parsing backend health payloads (`status`, `service`, `version`, `timestamp`).
   - `ApiClient`: Real backend health check client targeting `GET /api/v1/health` with an ~8s timeout, graceful error recovery, and sealed `ApiResult` return types.
   - `WebsocketService`: **Documented stub for Phase 9**. Emits no fake ticks or mock telemetry.

5. **Screens (`lib/screens/`)**:
   - `HomeScreen`: Hero introduction, real system health card with retry mechanism, and Phase 2+ capability preview.
   - `RoadmapScreen`: Phase 2 through Phase 11 breakdown reflecting the project delivery plan.
   - `PlatformScreen`: Skeleton placeholder representing future operations dashboard.

---

## 🛡️ Honest Status Messaging Philosophy

A strict design and architectural principle of AI TrafficOS is **complete transparency**:
- **Zero Mock Metrics**: No fake vehicle counts, simulated 99.9% uptime badges, or fabricated signal states.
- **Genuine Backend Health**: The system status card displays **Online** only when the real backend answers `GET /api/v1/health` with a healthy status. If unreachable, it displays **Offline** with the exact network or HTTP error.
- **Explicit Phase Badging**: All unreleased capabilities are explicitly labeled **Phase 2+** or **Upcoming**.

---

## 🔌 Intentionally Stubbed Components

- **`WebsocketService` (`lib/services/websocket_service.dart`)**:
  - Reserved for **Phase 9** (Real-Time Stream Engine).
  - In Phase 9, this service will ingest high-throughput live vehicle counts, camera detector events, signal phase switches, and AI Copilot dialogue.
  - In Phase 1, `connect()` logs a clear TODO and generates no simulated socket frames.

---

## 🚀 Getting Started & Running

### Prerequisites
- Flutter SDK 3.19+ (tested with Flutter 3.47.6 / Dart 3.13.5)
- Android SDK, iOS Xcode, or Web/Desktop tooling enabled

### 1. Install Dependencies
```bash
cd mobile
flutter pub get
```

### 2. Run the App (Default Local Backend: `http://localhost:8000`)
```bash
flutter run
```

### 3. Run with Custom Backend Target
Pass the `--dart-define=API_URL` flag to configure the API base URL:
```bash
flutter run --dart-define=API_URL=http://192.168.1.100:8000
```
Or for production/staging environments:
```bash
flutter run --dart-define=API_URL=https://api.trafficos.example.com
```

### 4. Run Analysis & Tests
```bash
flutter analyze
flutter test
```
