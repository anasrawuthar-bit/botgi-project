import 'package:flutter/material.dart';

class PriorityBadge extends StatelessWidget {
  const PriorityBadge({
    super.key,
    required this.priority,
    this.label,
    this.compact = false,
  });

  final String priority;
  final String? label;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final cleanPriority = priority.toLowerCase().trim();
    final displayText = label ?? _defaultLabel(cleanPriority);
    final (bg, fg, icon) = _styleForPriority(cleanPriority);

    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 7 : 9,
        vertical: compact ? 2 : 4,
      ),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: fg.withValues(alpha: 0.35), width: 0.8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: compact ? 11 : 13, color: fg),
            const SizedBox(width: 4),
          ],
          Text(
            displayText,
            style: TextStyle(
              color: fg,
              fontSize: compact ? 10 : 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  String _defaultLabel(String p) {
    switch (p) {
      case 'urgent':
        return 'URGENT';
      case 'high':
        return 'HIGH';
      case 'low':
        return 'LOW';
      default:
        return 'MEDIUM';
    }
  }

  (Color, Color, IconData?) _styleForPriority(String p) {
    switch (p) {
      case 'urgent':
        return (const Color(0xFFFFEBEE), const Color(0xFFC62828), Icons.warning_amber_rounded);
      case 'high':
        return (const Color(0xFFFFF3E0), const Color(0xFFE65100), Icons.arrow_upward_rounded);
      case 'low':
        return (const Color(0xFFECEFF1), const Color(0xFF546E7A), null);
      default:
        return (const Color(0xFFE3F2FD), const Color(0xFF1565C0), null);
    }
  }
}
