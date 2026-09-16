import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.status, this.compact = false});

  final String status;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final styles = _stylesForStatus(status);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 3 : 4,
      ),
      decoration: BoxDecoration(
        color: styles.bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        status,
        style: TextStyle(
          color: styles.fg,
          fontSize: compact ? 11 : 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  _StatusStyles _stylesForStatus(String value) {
    switch (value) {
      case 'Closed':
        return const _StatusStyles(AppColors.successBg, AppColors.successFg);
      case 'Pending':
        return const _StatusStyles(AppColors.warningBg, AppColors.warningFg);
      default:
        return const _StatusStyles(AppColors.infoBg, AppColors.infoFg);
    }
  }
}

class _StatusStyles {
  const _StatusStyles(this.bg, this.fg);

  final Color bg;
  final Color fg;
}
