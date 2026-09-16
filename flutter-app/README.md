# El72 Deals

**Real-Time Price Tracking & Deal Detection App**

A modern Flutter application for monitoring product prices across e-commerce platforms, featuring real-time alerts, deal notifications, and a sleek fintech-inspired interface.

## ✨ Features

### 🎯 Core Functionality
- **Real-Time Price Tracking**: Monitor product prices across multiple e-commerce platforms
- **Smart Deal Detection**: Automatic identification of price drops and special offers
- **Custom Alerts**: Set up personalized price alerts for specific products
- **Multi-Platform Support**: Track prices on Amazon, Jumia, Carrefour, and more

### 🎨 User Interface
- **Fintech Design System**: Navy blue (#0F172A) primary with emerald (#10B981) accents
- **High-Frequency Trading UI**: Card-based feed layout resembling trading platforms
- **Dark/Light Mode**: Automatic theme adaptation
- **Responsive Design**: Optimized for mobile and web platforms

### 📊 Dashboard Components
- **Market Pulse Header**: Live stats showing active alerts, daily deals, and savings
- **Deal Cards**: Compact cards with product images, pricing, and discount badges
- **Scrollable Feed**: Infinite scroll through live market data
- **Quick Actions**: Floating action button for creating new trackers

## 🏗️ Architecture

### Tech Stack
- **Frontend**: Flutter (Dart) with Material Design 3
- **State Management**: Riverpod for reactive state management
- **UI Framework**: Custom component library with reusable widgets
- **Backend**: Event-driven microservices (Redis Streams)
- **Database**: TimescaleDB (time-series) + PostgreSQL
- **Deployment**: Docker containerized services

### Project Structure
```
lib/
├── core/                    # Core utilities and styles
│   └── styles/
│       └── app_colors.dart  # Fintech color palette
├── ui/                      # User interface components
│   ├── widgets/            # Reusable UI components
│   │   ├── deal_card.dart         # Product deal cards
│   │   └── market_pulse_header.dart # Stats header
│   ├── dashboard/           # Main dashboard screens
│   ├── auth/               # Authentication screens
│   └── common/             # Shared UI components
├── data/                   # Data layer
│   ├── repositories/       # API communication
│   └── providers.dart      # Riverpod providers
└── routing/               # Navigation and routes
```

## 🚀 Getting Started

### Prerequisites
- Flutter SDK (3.9.2+)
- Dart SDK (bundled with Flutter)
- Android Studio / VS Code with Flutter extensions
- Git

### Environment Setup
```bash
# Activate project environment (required)
& "D:/repos/Project Aincrad/projects/Scripts/Activate.ps1"

# Navigate to Flutter app
cd flutter-app

# Install dependencies
flutter pub get

# Run code analysis
flutter analyze

# Run tests
flutter test
```

### Running the App

#### Development Mode
```bash
# Run on connected device/emulator
flutter run

# Run on specific device
flutter run -d chrome      # Web browser
flutter run -d windows     # Windows desktop
flutter run -d android     # Android device
```

#### Build for Production
```bash
# Build APK for Android
flutter build apk --release

# Build for web
flutter build web --release

# Build for Windows
flutter build windows --release
```

## 🎨 Design System

### Color Palette
```dart
// Primary Colors - Fintech Theme
Color primary = Color(0xFF0F172A);    // Dark Navy
Color secondary = Color(0xFF10B981);  // Emerald Green

// Semantic Colors
Color priceUp = Color(0xFFEF4444);    // Red for price increases
Color priceDown = Color(0xFF10B981);  // Green for deals

// Typography
TextStyle priceText = GoogleFonts.jetBrainsMono();  // Monospaced prices
TextStyle bodyText = GoogleFonts.ibmPlexSans();     // UI text
```

### Component Library
- **DealCard**: Product display with image, pricing, and discount badge
- **MarketPulseHeader**: Statistics dashboard header
- **CreateTrackerSheet**: Bottom sheet for adding new price trackers

## 📱 Testing

### Unit Tests
```bash
flutter test
```

### Integration Tests
```bash
flutter test integration_test/
```

### Manual Testing Checklist
- [ ] App launches without errors
- [ ] Deals tab shows market pulse header
- [ ] Deal cards display with correct pricing
- [ ] FAB opens tracker creation sheet
- [ ] Dark/light mode switching works
- [ ] Responsive layout on different screen sizes

## 🔄 Recent Updates (v2.0 MVP)

### Phase 1: Complete Rebranding ✅
- Renamed from the previous clinic app to El72 (price intelligence)
- Removed all medical-themed assets and terminology
- Updated package names and configuration files

### Phase 2: Fintech Design System ✅
- Implemented navy/emerald color palette
- Added JetBrains Mono font for price display
- Created reusable UI components (DealCard, MarketPulseHeader)
- Updated ThemeData with custom colors and typography

### Phase 3: Dashboard Overhaul ✅
- Replaced clinic GridView with high-frequency trading feed
- Implemented CustomScrollView with SliverAppBar
- Added mock data for immediate UI testing
- Enhanced FAB functionality across multiple tabs

## 🤝 Contributing

### Development Workflow
1. **Environment Setup**: Always run the activation script first
2. **Branch Strategy**: Create feature branches from `main`
3. **Code Style**: Follow Flutter linting rules
4. **Testing**: Add tests for new features
5. **Commits**: Use conventional commit messages

### Code Standards
- **SOLID Principles**: Clean architecture with dependency injection
- **Error Handling**: Fail fast with proper logging
- **Security**: Never commit secrets, validate all inputs
- **Performance**: Optimize for smooth scrolling and fast loads

## 📈 Roadmap

### Phase 4: Backend Integration (Current)
- Connect to Redis Streams for real-time data
- Implement API communication layer
- Add authentication and user management

### Phase 5: Advanced Features
- Push notifications for price alerts
- Advanced filtering and sorting
- Historical price charts
- Multi-currency support

### Phase 6: Production Deployment
- Docker containerization
- CI/CD pipeline setup
- Monitoring and analytics

## 📄 License

This project is part of the El72 ecosystem. See individual service licenses for details.

## 🆘 Support

For questions or issues:
- Check existing GitHub issues
- Review the architecture documentation
- Contact the development team

---

**Built with ❤️ using Flutter**
