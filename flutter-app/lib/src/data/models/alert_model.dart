class Alert {
  final String id;
  final String targetUrl;
  final double targetPrice;
  final String title;
  final double currentPrice;
  final bool isActive;

  Alert({
    required this.id,
    required this.targetUrl,
    required this.targetPrice,
    required this.title,
    required this.currentPrice,
    required this.isActive,
  });

  factory Alert.fromJson(Map<String, dynamic> json) {
    return Alert(
      id: json['id'] as String,
      targetUrl: json['product_url'] as String,
      targetPrice: (json['target_price'] as num).toDouble(),
      title: json['title'] ?? '',
      currentPrice: (json['current_price'] as num?)?.toDouble() ?? 0.0,
      isActive: json['status'] == 'active',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'product_url': targetUrl,
      'target_price': targetPrice,
      'title': title,
      'current_price': currentPrice,
      'status': isActive ? 'active' : 'inactive',
    };
  }
}