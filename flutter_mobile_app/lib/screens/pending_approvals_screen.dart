import 'package:flutter/material.dart';

import '../models/management_models.dart';
import '../services/management_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class PendingApprovalsScreen extends StatefulWidget {
  const PendingApprovalsScreen({super.key, required this.managementService});

  final ManagementService managementService;

  @override
  State<PendingApprovalsScreen> createState() => _PendingApprovalsScreenState();
}

class _PendingApprovalsScreenState extends State<PendingApprovalsScreen> {
  late Future<PendingApprovalsResponse> _approvalsFuture;
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _approvalsFuture = widget.managementService.fetchPendingApprovals();
  }

  Future<void> _reload() async {
    setState(() {
      _approvalsFuture = widget.managementService.fetchPendingApprovals();
    });
    await _approvalsFuture;
  }

  Future<String?> _askNote({
    required String title,
    required String hintText,
  }) async {
    final controller = TextEditingController();
    final note = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: TextField(
          controller: controller,
          maxLines: 3,
          decoration: InputDecoration(hintText: hintText),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('Submit'),
          ),
        ],
      ),
    );
    controller.dispose();
    return note;
  }

  Future<void> _respond(PendingApprovalItem item, String action) async {
    if (_isSubmitting) {
      return;
    }

    String note = '';
    if (action == 'reject') {
      final entered = await _askNote(
        title: 'Reject ${item.jobCode}',
        hintText: 'Optional reason',
      );
      if (entered == null) {
        return;
      }
      note = entered;
    }

    setState(() {
      _isSubmitting = true;
    });
    try {
      final message = await widget.managementService.respondPendingApproval(
        assignmentId: item.id,
        action: action,
        note: note,
      );
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
      await _reload();
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: AppColors.warningFg,
          content: Text(error.toString().replaceFirst('Exception: ', '')),
        ),
      );
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
      appBar: AppBar(title: const Text('Pending Approvals')),
      body: SafeArea(
        child: FutureBuilder<PendingApprovalsResponse>(
          future: _approvalsFuture,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }

            if (snapshot.hasError) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        snapshot.error.toString().replaceFirst('Exception: ', ''),
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: AppColors.warningFg),
                      ),
                      const SizedBox(height: 10),
                      FilledButton(onPressed: _reload, child: const Text('Retry')),
                    ],
                  ),
                ),
              );
            }

            final data = snapshot.data ?? PendingApprovalsResponse(canAct: false, approvals: const []);

            return RefreshIndicator(
              onRefresh: _reload,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
                children: [
                  Text(
                    '${data.approvals.length} pending',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 10),
                  if (data.approvals.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Center(child: Text('No pending approvals.')),
                    )
                  else
                    ...data.approvals.map(
                      (item) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppSurfaceCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                                Text(
                                  item.jobCode,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 16,
                                  ),
                                ),
                              const SizedBox(height: 6),
                              Text('Customer: ${item.customerName}'),
                              Text('Phone: ${item.customerPhone}'),
                              Text('Device: ${item.device}'),
                              Text('Job Status: ${item.jobStatus}'),
                              if (item.technician.isNotEmpty) Text('Technician: ${item.technician}'),
                              const SizedBox(height: 4),
                              Text(
                                'Requested: ${item.createdAt}',
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                              if (data.canAct) ...[
                                const SizedBox(height: 10),
                                Row(
                                  children: [
                                    Expanded(
                                      child: FilledButton.tonalIcon(
                                        onPressed: _isSubmitting
                                            ? null
                                            : () => _respond(item, 'accept'),
                                        icon: const Icon(Icons.check_circle_outline),
                                        label: const Text('Accept'),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: FilledButton.tonalIcon(
                                        onPressed: _isSubmitting
                                            ? null
                                            : () => _respond(item, 'reject'),
                                        icon: const Icon(Icons.cancel_outlined),
                                        label: const Text('Reject'),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}
