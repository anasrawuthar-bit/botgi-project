import 'package:flutter/material.dart';

import '../config/app_config.dart';
import '../services/auth_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({
    super.key,
    required this.authService,
    required this.onLogout,
  });

  final AuthService authService;
  final Future<void> Function() onLogout;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late String _selectedMode;
  late TextEditingController _customUrlController;
  bool _isSaving = false;

  @override
  void initState() {
    super.initState();
    _selectedMode = AppConfig.mode;
    _customUrlController = TextEditingController(text: AppConfig.customBaseUrl);
  }

  @override
  void dispose() {
    _customUrlController.dispose();
    super.dispose();
  }

  Future<void> _saveServerSettings() async {
    if (_selectedMode == AppConfig.customMode) {
      final normalized = AppConfig.normalizeBaseUrl(_customUrlController.text);
      if (normalized.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppColors.warningFg,
            content: Text('Enter a valid custom URL before saving.'),
          ),
        );
        return;
      }
    }

    setState(() {
      _isSaving = true;
    });

    await AppConfig.setMode(_selectedMode);
    if (_selectedMode == AppConfig.customMode) {
      await AppConfig.setCustomBaseUrl(_customUrlController.text);
    }

    if (!mounted) {
      return;
    }
    setState(() {
      _isSaving = false;
    });

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Server updated to ${AppConfig.baseUrl}')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.authService.currentUser ?? {};
    final username = (user['username'] ?? '').toString();
    final role = (user['role'] ?? '').toString();
    final techId = (user['technician_id'] ?? '').toString();

    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Profile', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 14),
          AppSurfaceCard(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Username: $username'),
                const SizedBox(height: 8),
                Text('Role: ${role.toUpperCase()}'),
                if (techId.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text('Technician ID: $techId'),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          AppSurfaceCard(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'API Server',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ChoiceChip(
                      label: const Text('Dev'),
                      selected: _selectedMode == AppConfig.devMode,
                      onSelected: (_) {
                        setState(() {
                          _selectedMode = AppConfig.devMode;
                        });
                      },
                    ),
                    ChoiceChip(
                      label: const Text('Prod'),
                      selected: _selectedMode == AppConfig.prodMode,
                      onSelected: (_) {
                        setState(() {
                          _selectedMode = AppConfig.prodMode;
                        });
                      },
                    ),
                    ChoiceChip(
                      label: const Text('Custom'),
                      selected: _selectedMode == AppConfig.customMode,
                      onSelected: (_) {
                        setState(() {
                          _selectedMode = AppConfig.customMode;
                        });
                      },
                    ),
                  ],
                ),
                if (_selectedMode == AppConfig.customMode) ...[
                  const SizedBox(height: 10),
                  TextField(
                    controller: _customUrlController,
                    decoration: const InputDecoration(
                      labelText: 'Custom Base URL',
                      hintText: 'http://192.168.1.10:8000',
                    ),
                  ),
                ],
                const SizedBox(height: 10),
                Text('Active URL: ${AppConfig.baseUrl}'),
                const SizedBox(height: 10),
                FilledButton.tonalIcon(
                  onPressed: _isSaving ? null : _saveServerSettings,
                  icon: const Icon(Icons.save_outlined),
                  label: Text(_isSaving ? 'Saving...' : 'Save Server'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: widget.onLogout,
            icon: const Icon(Icons.logout),
            label: const Text('Logout'),
          ),
        ],
      ),
    );
  }
}
