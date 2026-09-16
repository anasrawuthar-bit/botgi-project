import 'package:flutter/material.dart';

import '../config/app_config.dart';
import '../services/auth_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.authService,
    required this.onLoginSuccess,
  });

  final AuthService authService;
  final VoidCallback onLoginSuccess;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  late String _selectedMode;
  late TextEditingController _customUrlController;

  bool _isSubmitting = false;
  bool _isSavingServer = false;
  String? _errorText;

  @override
  void initState() {
    super.initState();
    _selectedMode = AppConfig.mode;
    _customUrlController = TextEditingController(text: AppConfig.customBaseUrl);
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _customUrlController.dispose();
    super.dispose();
  }

  String _previewBaseUrl() {
    if (_selectedMode == AppConfig.customMode) {
      final normalized = AppConfig.normalizeBaseUrl(_customUrlController.text);
      return normalized.isEmpty ? 'Enter custom URL' : normalized;
    }
    if (_selectedMode == AppConfig.prodMode) {
      return AppConfig.prodBaseUrl;
    }
    return AppConfig.devBaseUrl;
  }

  Future<bool> _applyServerSettings({required bool showFeedback}) async {
    if (_selectedMode == AppConfig.customMode) {
      final normalized = AppConfig.normalizeBaseUrl(_customUrlController.text);
      if (normalized.isEmpty) {
        setState(() {
          _errorText = 'Enter a valid custom server URL.';
        });
        return false;
      }
    }

    setState(() {
      _isSavingServer = true;
      _errorText = null;
    });

    try {
      await AppConfig.setMode(_selectedMode);
      if (_selectedMode == AppConfig.customMode) {
        await AppConfig.setCustomBaseUrl(_customUrlController.text);
      }

      if (!mounted) {
        return false;
      }

      setState(() {
        _isSavingServer = false;
      });

      if (showFeedback) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Server set to ${AppConfig.baseUrl}')),
        );
      }
      return true;
    } catch (_) {
      if (!mounted) {
        return false;
      }
      setState(() {
        _isSavingServer = false;
        _errorText = 'Failed to save server settings.';
      });
      return false;
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final serverReady = await _applyServerSettings(showFeedback: false);
    if (!serverReady) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorText = null;
    });

    try {
      await widget.authService.login(
        username: _usernameController.text.trim(),
        password: _passwordController.text,
      );
      if (!mounted) {
        return;
      }
      widget.onLoginSuccess();
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorText = error.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [
              AppColors.primarySoft,
              AppColors.background,
              Color(0xFFEFF2FF),
            ],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: AppSurfaceCard(
                  padding: const EdgeInsets.all(22),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: AppColors.primary,
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: const Icon(
                            Icons.support_agent_rounded,
                            color: Colors.white,
                            size: 28,
                          ),
                        ),
                        const SizedBox(height: 14),
                        Text(
                          'GI HOSTINGS',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Service Billing Mobile Login',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        const SizedBox(height: 14),
                        Text(
                          'Server Settings',
                          style: Theme.of(context).textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
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
                          TextFormField(
                            controller: _customUrlController,
                            decoration: const InputDecoration(
                              labelText: 'Custom Base URL',
                              hintText: 'http://192.168.1.10:8000',
                              prefixIcon: Icon(Icons.dns_outlined),
                            ),
                            onChanged: (_) {
                              setState(() {});
                            },
                          ),
                        ],
                        const SizedBox(height: 8),
                        Text(
                          'Active URL: ${_previewBaseUrl()}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: 8),
                        Align(
                          alignment: Alignment.centerRight,
                          child: FilledButton.tonalIcon(
                            onPressed: (_isSavingServer || _isSubmitting)
                                ? null
                                : () async {
                                    await _applyServerSettings(
                                      showFeedback: true,
                                    );
                                  },
                            icon: const Icon(Icons.save_outlined),
                            label: Text(
                              _isSavingServer ? 'Saving...' : 'Save Server',
                            ),
                          ),
                        ),
                        const SizedBox(height: 18),
                        TextFormField(
                          controller: _usernameController,
                          decoration: const InputDecoration(
                            labelText: 'Username',
                            prefixIcon: Icon(Icons.person_outline),
                          ),
                          validator: (value) {
                            if ((value ?? '').trim().isEmpty) {
                              return 'Enter username';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _passwordController,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Password',
                            prefixIcon: Icon(Icons.lock_outline),
                          ),
                          validator: (value) {
                            if ((value ?? '').isEmpty) {
                              return 'Enter password';
                            }
                            return null;
                          },
                        ),
                        if (_errorText != null) ...[
                          const SizedBox(height: 12),
                          Text(
                            _errorText!,
                            style: const TextStyle(color: AppColors.warningFg),
                          ),
                        ],
                        const SizedBox(height: 18),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton.icon(
                            onPressed: _isSubmitting ? null : _submit,
                            icon: _isSubmitting
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : const Icon(Icons.login_rounded),
                            label: Text(
                              _isSubmitting ? 'Signing in...' : 'Login',
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
