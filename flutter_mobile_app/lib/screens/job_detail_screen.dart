import 'package:flutter/material.dart';

import '../models/job_detail.dart';
import '../services/jobs_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/priority_badge.dart';
import '../widgets/status_pill.dart';

class JobDetailScreen extends StatefulWidget {
  const JobDetailScreen({
    super.key,
    required this.jobCode,
    required this.jobsService,
  });

  final String jobCode;
  final JobsService jobsService;

  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  late Future<JobDetail> _detailFuture;
  final TextEditingController _notesController = TextEditingController();

  bool _isActionBusy = false;
  bool _isNotesSaving = false;
  bool _isServiceBusy = false;
  bool _isEditingNotes = false;

  bool get _isBusy => _isActionBusy || _isNotesSaving || _isServiceBusy;

  @override
  void initState() {
    super.initState();
    _detailFuture = widget.jobsService.fetchJobDetail(widget.jobCode);
  }

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  void _syncNotesController(JobDetail detail) {
    if (_isEditingNotes) {
      return;
    }
    final remoteNotes = detail.technicianNotes;
    if (_notesController.text != remoteNotes) {
      _notesController.text = remoteNotes;
    }
  }

  void _showError(String message) {
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        backgroundColor: AppColors.warningFg,
        content: Text(message),
      ),
    );
  }

  void _showInfo(String message) {
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _refresh() async {
    setState(() {
      _detailFuture = widget.jobsService.fetchJobDetail(widget.jobCode);
    });
    await _detailFuture;
  }

  Future<void> _runAction(JobActionOption action) async {
    setState(() {
      _isActionBusy = true;
    });
    try {
      final message = await widget.jobsService.performJobAction(
        jobCode: widget.jobCode,
        action: action.key,
      );
      _showInfo(message);
      await _refresh();
    } catch (error) {
      _showError(error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() {
          _isActionBusy = false;
        });
      }
    }
  }

  Future<void> _saveNotes(JobDetail detail) async {
    if (!detail.canEditNotes || _isNotesSaving) {
      return;
    }
    setState(() {
      _isNotesSaving = true;
    });
    try {
      final message = await widget.jobsService.updateJobNotes(
        jobCode: widget.jobCode,
        technicianNotes: _notesController.text.trim(),
      );
      _showInfo(message);
      if (!mounted) {
        return;
      }
      setState(() {
        _isEditingNotes = false;
      });
      await _refresh();
    } catch (error) {
      _showError(error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() {
          _isNotesSaving = false;
        });
      }
    }
  }

  Future<void> _openServiceLineEditor({JobServiceLine? line}) async {
    final result = await showModalBottomSheet<_ServiceLineInput>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => _ServiceLineEditorSheet(initialLine: line),
    );
    if (result == null) {
      return;
    }

    setState(() {
      _isServiceBusy = true;
    });
    try {
      final message = line == null
          ? await widget.jobsService.addServiceLine(
              jobCode: widget.jobCode,
              description: result.description,
              partCost: result.partCost,
              serviceCharge: result.serviceCharge,
              salesInvoiceNumber: result.salesInvoiceNumber,
            )
          : await widget.jobsService.updateServiceLine(
              jobCode: widget.jobCode,
              lineId: line.id,
              description: result.description,
              partCost: result.partCost,
              serviceCharge: result.serviceCharge,
              salesInvoiceNumber: result.salesInvoiceNumber,
            );
      _showInfo(message);
      await _refresh();
    } catch (error) {
      _showError(error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() {
          _isServiceBusy = false;
        });
      }
    }
  }

  Future<void> _deleteServiceLine(JobServiceLine line) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Service Line'),
        content: Text('Delete "${line.description}"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirmed != true) {
      return;
    }

    setState(() {
      _isServiceBusy = true;
    });
    try {
      final message = await widget.jobsService.deleteServiceLine(
        jobCode: widget.jobCode,
        lineId: line.id,
      );
      _showInfo(message);
      await _refresh();
    } catch (error) {
      _showError(error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() {
          _isServiceBusy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.jobCode),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _isBusy ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: FutureBuilder<JobDetail>(
        future: _detailFuture,
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
                    FilledButton(
                      onPressed: _refresh,
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
            );
          }

          final detail = snapshot.data;
          if (detail == null) {
            return const Center(child: Text('No data found.'));
          }

          _syncNotesController(detail);

          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 24),
              children: [
                AppSurfaceCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Text(
                              detail.customerName,
                              style: Theme.of(context).textTheme.titleLarge,
                            ),
                          ),
                          const SizedBox(width: 12),
                          StatusPill(status: detail.statusDisplay),
                        ],
                      ),
                      const SizedBox(height: 10),
                      _InfoLine(label: 'Phone', value: detail.customerPhone),
                      _InfoLine(
                        label: 'Device',
                        value:
                            '${detail.deviceType} ${detail.deviceBrand} ${detail.deviceModel}'.trim(),
                      ),
                      if (detail.deviceSerial.isNotEmpty)
                        _InfoLine(label: 'Serial', value: detail.deviceSerial),
                      if (detail.assignedTo.isNotEmpty)
                        _InfoLine(label: 'Assigned', value: detail.assignedTo),
                      if (detail.createdBy.isNotEmpty)
                        _InfoLine(label: 'Created By', value: detail.createdBy),
                      _InfoLine(
                        label: 'Under Warranty',
                        value: detail.isUnderWarranty ? 'Yes' : 'No',
                      ),
                      if (detail.estimatedAmount.isNotEmpty)
                        _InfoLine(
                          label: 'Estimated Amount',
                          value: 'Rs ${detail.estimatedAmount}',
                        ),
                      if (detail.estimatedDelivery.isNotEmpty)
                        _InfoLine(
                          label: 'Estimated Delivery',
                          value: detail.estimatedDelivery,
                        ),
                      if (detail.vyaparInvoiceNumber.isNotEmpty)
                        _InfoLine(
                          label: 'Invoice Number',
                          value: detail.vyaparInvoiceNumber,
                        ),
                      _InfoLine(label: 'Created At', value: detail.createdAt),
                      _InfoLine(label: 'Updated At', value: detail.updatedAt),
                    ],
                  ),
                ),
                if (detail.taskAssignment != null) ...[
                  const SizedBox(height: 12),
                  AppSurfaceCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'Task Assignment & Directives',
                              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                    fontWeight: FontWeight.w700,
                                  ),
                            ),
                            PriorityBadge(
                              priority: detail.taskAssignment!.priority,
                              label: detail.taskAssignment!.priorityDisplay,
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        if (detail.taskAssignment!.dueDate.isNotEmpty)
                          _InfoLine(
                            label: 'Due Date',
                            value: detail.taskAssignment!.dueDate,
                          ),
                        if (detail.taskAssignment!.assignedBy.isNotEmpty)
                          _InfoLine(
                            label: 'Assigned By',
                            value: '${detail.taskAssignment!.assignedBy} (${detail.taskAssignment!.assignedAt})',
                          ),
                        _InfoLine(
                          label: 'Status',
                          value: detail.taskAssignment!.statusDisplay,
                        ),
                        if (detail.taskAssignment!.instructions.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Text(
                            'Directives & Instructions',
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                          const SizedBox(height: 4),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: Colors.grey.shade100,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: Colors.grey.shade300),
                            ),
                            child: Text(
                              detail.taskAssignment!.instructions,
                              style: const TextStyle(fontSize: 13),
                            ),
                          ),
                        ],
                        if (detail.taskAssignment!.attachments.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          Text(
                            'Task Attachments (${detail.taskAssignment!.attachments.length})',
                            style: Theme.of(context).textTheme.titleSmall,
                          ),
                          const SizedBox(height: 6),
                          ...detail.taskAssignment!.attachments.map(
                            (att) => Padding(
                              padding: const EdgeInsets.only(bottom: 6),
                              child: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 8,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.blue.shade50.withValues(alpha: 0.5),
                                  borderRadius: BorderRadius.circular(8),
                                  border: Border.all(color: Colors.blue.shade200),
                                ),
                                child: Row(
                                  children: [
                                    const Icon(
                                      Icons.description_outlined,
                                      size: 18,
                                      color: Colors.blue,
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        att.fileName,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w600,
                                          fontSize: 13,
                                        ),
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ),
                                    if (att.fileSize > 0)
                                      Text(
                                        '${(att.fileSize / 1024).toStringAsFixed(1)} KB',
                                        style: const TextStyle(
                                          color: Colors.grey,
                                          fontSize: 11,
                                        ),
                                      ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                if (detail.reportedIssue.isNotEmpty ||
                    detail.additionalItems.isNotEmpty)
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Issue Details',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 8),
                          if (detail.reportedIssue.isNotEmpty) ...[
                            Text(
                              'Reported Issue',
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                            const SizedBox(height: 4),
                            Text(detail.reportedIssue),
                          ],
                          if (detail.additionalItems.isNotEmpty) ...[
                            const SizedBox(height: 10),
                            Text(
                              'Additional Items',
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                            const SizedBox(height: 4),
                            Text(detail.additionalItems),
                          ],
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 12),
                AppSurfaceCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Technician Notes',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          if (detail.canEditNotes && !_isEditingNotes)
                            TextButton.icon(
                              onPressed: _isNotesSaving
                                  ? null
                                  : () {
                                      setState(() {
                                        _isEditingNotes = true;
                                      });
                                    },
                              icon: const Icon(Icons.edit_outlined, size: 18),
                              label: const Text('Edit'),
                            ),
                        ],
                      ),
                      if (_isEditingNotes || detail.technicianNotes.isNotEmpty) ...[
                        TextField(
                          controller: _notesController,
                          readOnly: !(_isEditingNotes && detail.canEditNotes),
                          maxLines: 4,
                          decoration: const InputDecoration(
                            hintText: 'Add internal notes',
                          ),
                        ),
                      ] else
                        Text(
                          'No technician notes yet.',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      if (detail.canEditNotes && _isEditingNotes) ...[
                        const SizedBox(height: 10),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            TextButton(
                              onPressed: _isNotesSaving
                                  ? null
                                  : () {
                                      setState(() {
                                        _isEditingNotes = false;
                                        _notesController.text =
                                            detail.technicianNotes;
                                      });
                                    },
                              child: const Text('Cancel'),
                            ),
                            const SizedBox(width: 8),
                            FilledButton.icon(
                              onPressed: _isNotesSaving
                                  ? null
                                  : () => _saveNotes(detail),
                              icon: const Icon(Icons.save_outlined),
                              label: Text(
                                _isNotesSaving ? 'Saving...' : 'Save',
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
                if (detail.availableActions.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Actions',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 10),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: detail.availableActions
                                .map((action) {
                                  return FilledButton.tonalIcon(
                                    onPressed: _isActionBusy
                                        ? null
                                        : () => _runAction(action),
                                    icon: const Icon(Icons.bolt_rounded),
                                    label: Text(action.label),
                                  );
                                })
                                .toList(growable: false),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                AppSurfaceCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Financial Summary',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 10),
                      _FinanceRow(label: 'Parts', value: detail.partTotal),
                      _FinanceRow(label: 'Service', value: detail.serviceTotal),
                      _FinanceRow(label: 'Subtotal', value: detail.subtotal),
                      _FinanceRow(
                        label: 'Discount',
                        value: detail.discountAmount,
                      ),
                      const Divider(height: 18),
                      _FinanceRow(
                        label: 'Grand Total',
                        value: detail.grandTotal,
                        isBold: true,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'Service Lines',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            if (detail.canManageServiceLogs)
                              TextButton.icon(
                                onPressed: _isServiceBusy
                                    ? null
                                    : () => _openServiceLineEditor(),
                                icon: const Icon(Icons.add, size: 18),
                                label: const Text('Add'),
                              ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        if (detail.serviceLogs.isEmpty)
                          const Text('No service lines yet.')
                        else
                          ...detail.serviceLogs.map(
                            (line) => Padding(
                              padding: const EdgeInsets.only(bottom: 10),
                              child: Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: const Color(0xFFF8FAFC),
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(
                                    color: const Color(0xFFE5EAF1),
                                  ),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Expanded(
                                          child: Text(
                                            line.description,
                                            style: const TextStyle(
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                        ),
                                        if (line.isProductSale)
                                          Container(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: 8,
                                              vertical: 4,
                                            ),
                                            decoration: BoxDecoration(
                                              color: const Color(0xFFE0F2FE),
                                              borderRadius:
                                                  BorderRadius.circular(999),
                                            ),
                                            child: const Text(
                                              'Product',
                                              style: TextStyle(
                                                fontSize: 11,
                                                fontWeight: FontWeight.w700,
                                                color: AppColors.ink700,
                                              ),
                                            ),
                                          ),
                                      ],
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      'Part: Rs ${line.partCost} | Service: Rs ${line.serviceCharge}',
                                    ),
                                    if (line.isProductSale) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'Qty: ${line.productQuantity} | Unit: Rs ${line.productUnitPrice} | Line Total: Rs ${line.productLineTotal}',
                                        style: Theme.of(
                                          context,
                                        ).textTheme.bodySmall,
                                      ),
                                    ],
                                    if (line.salesInvoiceNumber.isNotEmpty) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'Invoice: ${line.salesInvoiceNumber}',
                                        style: Theme.of(
                                          context,
                                        ).textTheme.bodySmall,
                                      ),
                                    ],
                                    const SizedBox(height: 4),
                                    Text(
                                      'Created: ${line.createdAt}',
                                      style: Theme.of(
                                        context,
                                      ).textTheme.bodySmall,
                                    ),
                                    if (detail.canManageServiceLogs) ...[
                                      const SizedBox(height: 8),
                                      Row(
                                        mainAxisAlignment:
                                            MainAxisAlignment.end,
                                        children: [
                                          TextButton.icon(
                                            onPressed: _isServiceBusy ||
                                                    line.isProductSale
                                                ? null
                                                : () => _openServiceLineEditor(
                                                    line: line,
                                                  ),
                                            icon: const Icon(
                                              Icons.edit_outlined,
                                              size: 18,
                                            ),
                                            label: const Text('Edit'),
                                          ),
                                          const SizedBox(width: 4),
                                          TextButton.icon(
                                            onPressed: _isServiceBusy
                                                ? null
                                                : () => _deleteServiceLine(
                                                    line,
                                                  ),
                                            icon: const Icon(
                                              Icons.delete_outline,
                                              size: 18,
                                            ),
                                            label: const Text('Delete'),
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
                  ),
                ),
                if (detail.feedbackRating > 0 || detail.feedbackComment.isNotEmpty)
                  ...[
                    const SizedBox(height: 12),
                    AppSurfaceCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Customer Feedback',
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: 10),
                          if (detail.feedbackRating > 0)
                            _InfoLine(
                              label: 'Rating',
                              value: '${detail.feedbackRating}/5',
                            ),
                          if (detail.feedbackComment.isNotEmpty)
                            _InfoLine(
                              label: 'Comment',
                              value: detail.feedbackComment,
                            ),
                          if (detail.feedbackDate.isNotEmpty)
                            _InfoLine(
                              label: 'Feedback Date',
                              value: detail.feedbackDate,
                            ),
                        ],
                      ),
                    ),
                  ],
                const SizedBox(height: 12),
                AppSurfaceCard(
                  padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Status Timeline',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 12),
                      if (detail.timeline.isEmpty)
                        const Text('No timeline entries.')
                      else
                        ...List.generate(detail.timeline.length, (index) {
                          final item = detail.timeline[index];
                          final isLast = index == detail.timeline.length - 1;
                          return _TimelineItem(event: item, isLast: isLast);
                        }),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
class _InfoLine extends StatelessWidget {
  const _InfoLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: RichText(
        text: TextSpan(
          style: Theme.of(context).textTheme.bodyMedium,
          children: [
            TextSpan(
              text: '$label: ',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            TextSpan(text: value),
          ],
        ),
      ),
    );
  }
}

class _FinanceRow extends StatelessWidget {
  const _FinanceRow({
    required this.label,
    required this.value,
    this.isBold = false,
  });

  final String label;
  final String value;
  final bool isBold;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontWeight: isBold ? FontWeight.w700 : FontWeight.w500,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: style),
          Text('Rs $value', style: style),
        ],
      ),
    );
  }
}

class _TimelineItem extends StatelessWidget {
  const _TimelineItem({required this.event, required this.isLast});

  final JobTimelineEvent event;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 24,
          child: Column(
            children: [
              Container(
                width: 10,
                height: 10,
                decoration: const BoxDecoration(
                  color: Color(0xFF0A7C86),
                  shape: BoxShape.circle,
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 62,
                  margin: const EdgeInsets.only(top: 2),
                  color: const Color(0xFFD2DCE9),
                ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE5EAF1)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    event.label,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${event.timestamp} - ${event.user}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  if (event.details.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(event.details),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ServiceLineInput {
  const _ServiceLineInput({
    required this.description,
    required this.partCost,
    required this.serviceCharge,
    required this.salesInvoiceNumber,
  });

  final String description;
  final String partCost;
  final String serviceCharge;
  final String salesInvoiceNumber;
}

class _ServiceLineEditorSheet extends StatefulWidget {
  const _ServiceLineEditorSheet({this.initialLine});

  final JobServiceLine? initialLine;

  @override
  State<_ServiceLineEditorSheet> createState() => _ServiceLineEditorSheetState();
}

class _ServiceLineEditorSheetState extends State<_ServiceLineEditorSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _descriptionController;
  late final TextEditingController _partCostController;
  late final TextEditingController _serviceChargeController;
  late final TextEditingController _invoiceController;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialLine;
    _descriptionController = TextEditingController(
      text: initial?.description ?? '',
    );
    _partCostController = TextEditingController(text: initial?.partCost ?? '0');
    _serviceChargeController = TextEditingController(
      text: initial?.serviceCharge ?? '0',
    );
    _invoiceController = TextEditingController(
      text: initial?.salesInvoiceNumber ?? '',
    );
  }

  @override
  void dispose() {
    _descriptionController.dispose();
    _partCostController.dispose();
    _serviceChargeController.dispose();
    _invoiceController.dispose();
    super.dispose();
  }

  String? _validateAmount(String? value) {
    final text = (value ?? '').trim();
    if (text.isEmpty) {
      return null;
    }
    if (num.tryParse(text) == null) {
      return 'Enter a valid amount';
    }
    return null;
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    Navigator.of(context).pop(
      _ServiceLineInput(
        description: _descriptionController.text.trim(),
        partCost: _partCostController.text.trim().isEmpty
            ? '0'
            : _partCostController.text.trim(),
        serviceCharge: _serviceChargeController.text.trim().isEmpty
            ? '0'
            : _serviceChargeController.text.trim(),
        salesInvoiceNumber: _invoiceController.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.fromLTRB(16, 10, 16, bottomInset + 16),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                widget.initialLine == null
                    ? 'Add Service Line'
                    : 'Edit Service Line',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _descriptionController,
                decoration: const InputDecoration(labelText: 'Description'),
                validator: (value) {
                  if ((value ?? '').trim().isEmpty) {
                    return 'Description is required';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _partCostController,
                decoration: const InputDecoration(labelText: 'Part Cost'),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                validator: _validateAmount,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _serviceChargeController,
                decoration: const InputDecoration(labelText: 'Service Charge'),
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                validator: _validateAmount,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _invoiceController,
                decoration: const InputDecoration(
                  labelText: 'Sales Invoice Number',
                ),
              ),
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.save_outlined),
                  label: Text(
                    widget.initialLine == null ? 'Add Line' : 'Save Changes',
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
