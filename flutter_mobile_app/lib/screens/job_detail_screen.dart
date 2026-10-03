import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/job_detail.dart';
import '../services/jobs_service.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/priority_badge.dart';
import '../widgets/status_pill.dart';

class JobDetailScreen extends StatefulWidget {
  const JobDetailScreen({
    super.key,
    required this.jobCode,
    required this.jobsService,
    this.tasksService,
  });

  final String jobCode;
  final JobsService jobsService;
  final TasksService? tasksService;

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
  bool _isChecklistSaving = false;

  Map<String, dynamic> _checklistAnswers = {};
  bool _checklistInitialized = false;

  bool get _isBusy =>
      _isActionBusy || _isNotesSaving || _isServiceBusy || _isChecklistSaving;

  TasksService get _tasksService =>
      widget.tasksService ?? TasksService(widget.jobsService.authService);

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

  void _syncChecklistAnswers(JobDetail detail) {
    if (_checklistInitialized) {
      return;
    }
    _checklistAnswers = Map<String, dynamic>.from(detail.checklistAnswers);
    // Also pull initial values from schema if not present in answers
    for (final field in detail.checklistSchema) {
      if (!_checklistAnswers.containsKey(field.key) && field.value != null) {
        _checklistAnswers[field.key] = field.value;
      }
    }
    _checklistInitialized = true;
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
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  Future<void> _refresh() async {
    setState(() {
      _checklistInitialized = false;
      _detailFuture = widget.jobsService.fetchJobDetail(widget.jobCode);
    });
    await _detailFuture;
  }

  Future<void> _makeCall(String phoneNumber) async {
    final clean = phoneNumber.replaceAll(RegExp(r'[^\d+]'), '');
    if (clean.isEmpty) {
      _showError('No customer phone number available.');
      return;
    }
    final uri = Uri.parse('tel:$clean');
    try {
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri);
      } else {
        _showError('Unable to open phone dialer.');
      }
    } catch (_) {
      _showError('Unable to open phone dialer.');
    }
  }

  Future<void> _openWhatsApp(String phoneNumber) async {
    var digits = phoneNumber.replaceAll(RegExp(r'[^\d]'), '');
    if (digits.isEmpty) {
      _showError('No customer phone number available.');
      return;
    }
    if (digits.length == 10) {
      digits = '91$digits';
    }
    final uri = Uri.parse('https://wa.me/$digits');
    try {
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        _showError('WhatsApp is not installed or cannot open link.');
      }
    } catch (_) {
      _showError('Unable to open WhatsApp.');
    }
  }

  void _copyToClipboard(String text, String label) {
    Clipboard.setData(ClipboardData(text: text));
    _showInfo('$label copied to clipboard');
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

  void _showAllActionsSheet(List<JobActionOption> actions) {
    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Workflow Actions',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => Navigator.of(context).pop(),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                ...actions.map((act) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton.tonalIcon(
                        onPressed: () {
                          Navigator.of(context).pop();
                          _runAction(act);
                        },
                        icon: const Icon(Icons.bolt_rounded, size: 20),
                        label: Text(act.label),
                        style: FilledButton.styleFrom(
                          alignment: Alignment.centerLeft,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 14,
                          ),
                        ),
                      ),
                    ),
                  );
                }),
              ],
            ),
          ),
        );
      },
    );
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

  Future<void> _saveChecklist() async {
    if (_isChecklistSaving) {
      return;
    }
    setState(() {
      _isChecklistSaving = true;
    });
    try {
      final message = await widget.jobsService.saveJobChecklist(
        jobCode: widget.jobCode,
        answers: _checklistAnswers,
      );
      _showInfo(message);
      await _refresh();
    } catch (error) {
      _showError(error.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() {
          _isChecklistSaving = false;
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

  Future<void> _openCreateDirectiveSheet() async {
    final created = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => _CreateJobDirectiveSheet(
        jobCode: widget.jobCode,
        tasksService: _tasksService,
      ),
    );

    if (created == true) {
      _showInfo('Directive created successfully.');
      await _refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
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
          _syncChecklistAnswers(detail);

          return Stack(
            children: [
              RefreshIndicator(
                onRefresh: _refresh,
                child: ListView(
                  padding: EdgeInsets.fromLTRB(
                    14,
                    12,
                    14,
                    detail.availableActions.isNotEmpty ? 100 : 32,
                  ),
                  children: [
                    _buildHeroCard(detail),
                    const SizedBox(height: 12),
                    _buildBenchAccessCard(detail),
                    const SizedBox(height: 12),
                    _buildReportedIssueCard(detail),
                    if (detail.checklistSchema.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      _buildChecklistCard(detail),
                    ],
                    const SizedBox(height: 12),
                    _buildTasksCard(detail),
                    const SizedBox(height: 12),
                    _buildServiceLinesCard(detail),
                    const SizedBox(height: 12),
                    _buildFinancialSummaryCard(detail),
                    const SizedBox(height: 12),
                    _buildTechnicianNotesCard(detail),
                    if (detail.feedbackRating > 0 ||
                        detail.feedbackComment.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      _buildFeedbackCard(detail),
                    ],
                    const SizedBox(height: 12),
                    _buildTimelineCard(detail),
                  ],
                ),
              ),
              if (detail.availableActions.isNotEmpty)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: _buildStickyActionBar(detail),
                ),
            ],
          );
        },
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // SECTION BUILDERS
  // ---------------------------------------------------------------------------

  Widget _buildHeroCard(JobDetail detail) {
    final deviceTitle =
        '${detail.deviceBrand} ${detail.deviceModel}'.trim();
    final hasPhone = detail.customerPhone.isNotEmpty;

    return AppSurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (detail.deviceType.isNotEmpty)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 2,
                        ),
                        margin: const EdgeInsets.only(bottom: 6),
                        decoration: BoxDecoration(
                          color: const Color(0xFFE2E8F0),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          detail.deviceType.toUpperCase(),
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink700,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ),
                    Text(
                      deviceTitle.isNotEmpty ? deviceTitle : 'Unknown Device',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w800,
                            fontSize: 20,
                          ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              StatusPill(status: detail.statusDisplay),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.person_rounded,
                  size: 20,
                  color: AppColors.ink500,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        detail.customerName.isNotEmpty
                            ? detail.customerName
                            : 'Walk-in Customer',
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 14,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (hasPhone)
                        Text(
                          detail.customerPhone,
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.ink500,
                          ),
                        ),
                    ],
                  ),
                ),
                if (hasPhone) ...[
                  IconButton.filledTonal(
                    onPressed: () => _makeCall(detail.customerPhone),
                    icon: const Icon(Icons.phone_outlined, size: 18),
                    tooltip: 'Call Customer',
                    style: IconButton.styleFrom(
                      backgroundColor: Colors.blue.shade50,
                      foregroundColor: Colors.blue.shade700,
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton.filledTonal(
                    onPressed: () => _openWhatsApp(detail.customerPhone),
                    icon: const Icon(Icons.chat_bubble_outline, size: 18),
                    tooltip: 'WhatsApp Customer',
                    style: IconButton.styleFrom(
                      backgroundColor: Colors.green.shade50,
                      foregroundColor: Colors.green.shade700,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _buildChipBadge(
                icon: Icons.shield_outlined,
                label: detail.isUnderWarranty ? 'Under Warranty' : 'Out of Warranty',
                bgColor: detail.isUnderWarranty ? const Color(0xFFE2F8ED) : const Color(0xFFF1F5F9),
                fgColor: detail.isUnderWarranty ? const Color(0xFF0E8E54) : AppColors.ink500,
              ),
              if (detail.deviceSerial.isNotEmpty)
                InkWell(
                  onTap: () => _copyToClipboard(detail.deviceSerial, 'Serial Number'),
                  borderRadius: BorderRadius.circular(6),
                  child: _buildChipBadge(
                    icon: Icons.fingerprint_rounded,
                    label: 'S/N: ${detail.deviceSerial}',
                    bgColor: const Color(0xFFF1F5F9),
                    fgColor: AppColors.ink700,
                  ),
                ),
              if (detail.assignedTo.isNotEmpty)
                _buildChipBadge(
                  icon: Icons.engineering_outlined,
                  label: 'Tech: ${detail.assignedTo}',
                  bgColor: const Color(0xFFF1F5F9),
                  fgColor: AppColors.ink700,
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBenchAccessCard(JobDetail detail) {
    final hasPassword = detail.devicePassword.isNotEmpty;
    final hasRack = detail.rackLocation.isNotEmpty || detail.rackShort.isNotEmpty;
    final rackText = detail.rackLocation.isNotEmpty
        ? detail.rackLocation
        : (detail.rackShort.isNotEmpty ? detail.rackShort : 'Not assigned');

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.primary.withValues(alpha: 0.3)),
        boxShadow: [
          BoxShadow(
            color: AppColors.primary.withValues(alpha: 0.04),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(
                  Icons.build_circle_outlined,
                  size: 18,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(width: 8),
              const Text(
                'BENCH ACCESS & LOCATION',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: AppColors.primary,
                  letterSpacing: 0.6,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              // Passcode / Pattern column
              Expanded(
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: hasPassword
                        ? const Color(0xFFFEF3C7).withValues(alpha: 0.4)
                        : const Color(0xFFF8FAFC),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: hasPassword
                          ? const Color(0xFFF59E0B).withValues(alpha: 0.3)
                          : const Color(0xFFE2E8F0),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.key_rounded, size: 14, color: AppColors.ink500),
                          SizedBox(width: 4),
                          Text(
                            'PASSCODE / PIN',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink500,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Text(
                              hasPassword ? detail.devicePassword : 'No PIN / Open',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w800,
                                color: hasPassword
                                    ? const Color(0xFFB45309)
                                    : AppColors.ink500,
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          if (hasPassword)
                            InkWell(
                              onTap: () => _copyToClipboard(
                                detail.devicePassword,
                                'Device Passcode',
                              ),
                              child: const Padding(
                                padding: EdgeInsets.all(2),
                                child: Icon(
                                  Icons.copy_rounded,
                                  size: 16,
                                  color: Color(0xFFB45309),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 10),
              // Storage Rack column
              Expanded(
                child: Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: hasRack
                        ? const Color(0xFFE0F2FE).withValues(alpha: 0.5)
                        : const Color(0xFFF8FAFC),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: hasRack
                          ? const Color(0xFF38BDF8).withValues(alpha: 0.3)
                          : const Color(0xFFE2E8F0),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.shelves, size: 14, color: AppColors.ink500),
                          SizedBox(width: 4),
                          Text(
                            'STORAGE SHELF',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: AppColors.ink500,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        rackText,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: hasRack
                              ? const Color(0xFF0369A1)
                              : AppColors.ink500,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildReportedIssueCard(JobDetail detail) {
    final hasIssue = detail.reportedIssue.isNotEmpty;
    final hasAccessories = detail.additionalItems.isNotEmpty;

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFBEB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFDE68A)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(
                Icons.warning_amber_rounded,
                size: 18,
                color: Color(0xFFB45309),
              ),
              SizedBox(width: 8),
              Text(
                'REPORTED ISSUE',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFFB45309),
                  letterSpacing: 0.6,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            hasIssue ? detail.reportedIssue : 'No specific fault described.',
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: Color(0xFF78350F),
              height: 1.35,
            ),
          ),
          if (hasAccessories) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.7),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0xFFFDE68A)),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.inventory_2_outlined,
                    size: 14,
                    color: Color(0xFFB45309),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Accessories: ${detail.additionalItems}',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                        color: Color(0xFF92400E),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildChecklistCard(JobDetail detail) {
    final schema = detail.checklistSchema;
    final totalCount = schema.length;
    var completedCount = 0;

    for (final item in schema) {
      final val = _checklistAnswers[item.key];
      if (item.type == 'checkbox') {
        if (val == true || val == 'true' || val == 1) {
          completedCount++;
        }
      } else if (val != null && val.toString().trim().isNotEmpty) {
        completedCount++;
      }
    }

    final title = detail.checklistTitle.isNotEmpty
        ? detail.checklistTitle
        : 'Pre-Repair Inspection Checklist';

    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '$completedCount of $totalCount tests checked',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.ink500,
                      ),
                    ),
                  ],
                ),
              ),
              FilledButton.tonalIcon(
                onPressed: _isChecklistSaving ? null : _saveChecklist,
                icon: _isChecklistSaving
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.check_circle_outline, size: 16),
                label: Text(_isChecklistSaving ? 'Saving' : 'Save'),
                style: FilledButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: totalCount > 0 ? (completedCount / totalCount) : 0,
              backgroundColor: const Color(0xFFE2E8F0),
              color: completedCount == totalCount
                  ? const Color(0xFF10B981)
                  : AppColors.primary,
              minHeight: 6,
            ),
          ),
          const SizedBox(height: 12),
          ...schema.map((item) {
            final isChecked = _checklistAnswers[item.key] == true ||
                _checklistAnswers[item.key] == 'true' ||
                _checklistAnswers[item.key] == 1;

            if (item.type == 'checkbox') {
              return CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text(
                  item.label,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                subtitle: item.helpText.isNotEmpty
                    ? Text(
                        item.helpText,
                        style: const TextStyle(fontSize: 11, color: AppColors.ink500),
                      )
                    : null,
                value: isChecked,
                activeColor: AppColors.primary,
                onChanged: (val) {
                  setState(() {
                    _checklistAnswers[item.key] = val == true;
                  });
                },
              );
            }

            // Dropdown or text field item
            final currentVal = (_checklistAnswers[item.key] ?? '').toString();
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: TextFormField(
                initialValue: currentVal,
                decoration: InputDecoration(
                  labelText: item.label,
                  hintText: item.placeholder.isNotEmpty ? item.placeholder : null,
                  isDense: true,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
                onChanged: (val) {
                  _checklistAnswers[item.key] = val.trim();
                },
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildTasksCard(JobDetail detail) {
    final tasks = detail.tasks;
    final legacyTask = detail.taskAssignment;

    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Text(
                    'Directives & Tasks',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  if (tasks.isNotEmpty) ...[
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.primarySoft,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        '${tasks.length}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
              TextButton.icon(
                onPressed: _openCreateDirectiveSheet,
                icon: const Icon(Icons.add_task_rounded, size: 16),
                label: const Text('Add Directive'),
                style: TextButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (tasks.isEmpty && legacyTask == null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'No active directives for this job. Tap "+ Add Directive" to assign bench work or part requisitions.',
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.grey.shade600,
                ),
              ),
            )
          else ...[
            ...tasks.map((task) => _buildTaskItemTile(task)),
            if (tasks.isEmpty && legacyTask != null)
              _buildLegacyTaskTile(legacyTask),
          ],
        ],
      ),
    );
  }

  Widget _buildTaskItemTile(LinkedTaskItem task) {
    final isDone = task.status == 'done';
    final isInProgress = task.status == 'in_progress';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isDone
            ? const Color(0xFFF8FAFC)
            : (isInProgress
                ? const Color(0xFFEFF6FF)
                : const Color(0xFFFAFAFA)),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: isDone
              ? const Color(0xFFE2E8F0)
              : (isInProgress
                  ? const Color(0xFFBFDBFE)
                  : const Color(0xFFE2E8F0)),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  task.title,
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                    decoration: isDone ? TextDecoration.lineThrough : null,
                  ),
                ),
              ),
              PriorityBadge(
                priority: task.priority,
                label: task.priorityDisplay,
              ),
            ],
          ),
          if (task.description.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              task.description,
              style: const TextStyle(fontSize: 12, color: AppColors.ink700),
            ),
          ],
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                task.assignedTo.isNotEmpty
                    ? '👤 ${task.assignedTo}'
                    : '👤 Unassigned',
                style: const TextStyle(fontSize: 11, color: AppColors.ink500),
              ),
              StatusPill(status: task.statusDisplay),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildLegacyTaskTile(TaskAssignmentDetail task) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  task.instructions.isNotEmpty
                      ? task.instructions
                      : 'Assigned Directive',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
              PriorityBadge(
                priority: task.priority,
                label: task.priorityDisplay,
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                task.assignedBy.isNotEmpty ? 'By ${task.assignedBy}' : '',
                style: const TextStyle(fontSize: 11, color: AppColors.ink500),
              ),
              StatusPill(status: task.statusDisplay),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildServiceLinesCard(JobDetail detail) {
    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Parts & Service Lines',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  Text(
                    'Total: Rs ${detail.grandTotal}',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.primary,
                    ),
                  ),
                ],
              ),
              if (detail.canManageServiceLogs)
                FilledButton.tonalIcon(
                  onPressed: _isServiceBusy ? null : () => _openServiceLineEditor(),
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Add Line'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          if (detail.serviceLogs.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                'No parts or service charges recorded yet.',
                style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
              ),
            )
          else
            ...detail.serviceLogs.map(
              (line) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF8FAFC),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: const Color(0xFFE5EAF1)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              line.description,
                              style: const TextStyle(fontWeight: FontWeight.w700),
                            ),
                          ),
                          if (line.isProductSale)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                                vertical: 2,
                              ),
                              decoration: BoxDecoration(
                                color: const Color(0xFFE0F2FE),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: const Text(
                                'Inventory Part',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFF0369A1),
                                ),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Text(
                            'Part: Rs ${line.partCost}',
                            style: const TextStyle(fontSize: 12),
                          ),
                          const SizedBox(width: 12),
                          Text(
                            'Labor: Rs ${line.serviceCharge}',
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                      ),
                      if (line.isProductSale) ...[
                        const SizedBox(height: 2),
                        Text(
                          'Qty: ${line.productQuantity} | Unit: Rs ${line.productUnitPrice} | Line: Rs ${line.productLineTotal}',
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.ink500,
                          ),
                        ),
                      ],
                      if (detail.canManageServiceLogs && !line.isProductSale) ...[
                        const SizedBox(height: 6),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            TextButton.icon(
                              onPressed: _isServiceBusy
                                  ? null
                                  : () => _openServiceLineEditor(line: line),
                              icon: const Icon(Icons.edit_outlined, size: 16),
                              label: const Text('Edit'),
                              style: TextButton.styleFrom(
                                visualDensity: VisualDensity.compact,
                              ),
                            ),
                            const SizedBox(width: 4),
                            TextButton.icon(
                              onPressed: _isServiceBusy
                                  ? null
                                  : () => _deleteServiceLine(line),
                              icon: const Icon(Icons.delete_outline, size: 16),
                              label: const Text('Delete'),
                              style: TextButton.styleFrom(
                                visualDensity: VisualDensity.compact,
                                foregroundColor: Colors.red.shade700,
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
  }

  Widget _buildFinancialSummaryCard(JobDetail detail) {
    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Financial Breakdown',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 8),
          _FinanceRow(label: 'Parts Total', value: detail.partTotal),
          _FinanceRow(label: 'Labor & Service Total', value: detail.serviceTotal),
          _FinanceRow(label: 'Subtotal', value: detail.subtotal),
          _FinanceRow(label: 'Discount', value: detail.discountAmount),
          const Divider(height: 14),
          _FinanceRow(
            label: 'Grand Total',
            value: detail.grandTotal,
            isBold: true,
          ),
        ],
      ),
    );
  }

  Widget _buildTechnicianNotesCard(JobDetail detail) {
    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Technician Bench Notes',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
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
                  icon: const Icon(Icons.edit_outlined, size: 16),
                  label: const Text('Edit'),
                  style: TextButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          if (_isEditingNotes || detail.technicianNotes.isNotEmpty) ...[
            TextField(
              controller: _notesController,
              readOnly: !(_isEditingNotes && detail.canEditNotes),
              maxLines: 4,
              decoration: InputDecoration(
                hintText: 'Add internal bench notes or repair updates...',
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),
          ] else
            Text(
              'No technician notes added yet.',
              style: TextStyle(fontSize: 13, color: Colors.grey.shade600),
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
                            _notesController.text = detail.technicianNotes;
                          });
                        },
                  child: const Text('Cancel'),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _isNotesSaving ? null : () => _saveNotes(detail),
                  icon: const Icon(Icons.save_outlined, size: 18),
                  label: Text(_isNotesSaving ? 'Saving...' : 'Save Notes'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildFeedbackCard(JobDetail detail) {
    return AppSurfaceCard(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Customer Feedback',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 8),
          if (detail.feedbackRating > 0)
            Row(
              children: List.generate(5, (idx) {
                return Icon(
                  idx < detail.feedbackRating
                      ? Icons.star_rounded
                      : Icons.star_outline_rounded,
                  color: Colors.amber.shade700,
                  size: 20,
                );
              }),
            ),
          if (detail.feedbackComment.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              detail.feedbackComment,
              style: const TextStyle(fontStyle: FontStyle.italic),
            ),
          ],
          if (detail.feedbackDate.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'Received: ${detail.feedbackDate}',
              style: const TextStyle(fontSize: 11, color: AppColors.ink500),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildTimelineCard(JobDetail detail) {
    return AppSurfaceCard(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Status Timeline',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
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
    );
  }

  Widget _buildStickyActionBar(JobDetail detail) {
    final actions = detail.availableActions;
    if (actions.isEmpty) {
      return const SizedBox.shrink();
    }

    final firstAction = actions.first;
    final otherActions = actions.length > 1 ? actions.sublist(1) : <JobActionOption>[];

    return Container(
      padding: EdgeInsets.fromLTRB(
        16,
        10,
        16,
        MediaQuery.of(context).padding.bottom + 10,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            offset: const Offset(0, -3),
            blurRadius: 10,
          ),
        ],
        border: Border(
          top: BorderSide(color: Colors.grey.shade200),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: FilledButton.icon(
              onPressed: _isBusy ? null : () => _runAction(firstAction),
              icon: _isActionBusy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Icon(Icons.bolt_rounded, size: 20),
              label: Text(
                firstAction.label,
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
              ),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.primary,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
            ),
          ),
          if (otherActions.isNotEmpty) ...[
            const SizedBox(width: 10),
            OutlinedButton.icon(
              onPressed: _isBusy ? null : () => _showAllActionsSheet(actions),
              icon: const Icon(Icons.more_horiz_rounded),
              label: const Text('Actions'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildChipBadge({
    required IconData icon,
    required String label,
    required Color bgColor,
    required Color fgColor,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: fgColor),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: fgColor,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// HELPER COMPONENTS
// ---------------------------------------------------------------------------

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
      fontWeight: isBold ? FontWeight.w800 : FontWeight.w500,
      fontSize: isBold ? 15 : 13,
      color: isBold ? AppColors.ink900 : AppColors.ink700,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
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
                  color: AppColors.primary,
                  shape: BoxShape.circle,
                ),
              ),
              if (!isLast)
                Container(
                  width: 2,
                  height: 52,
                  margin: const EdgeInsets.only(top: 2),
                  color: const Color(0xFFD2DCE9),
                ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFE5EAF1)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    event.label,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${event.timestamp} • ${event.user}',
                    style: const TextStyle(fontSize: 11, color: AppColors.ink500),
                  ),
                  if (event.details.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      event.details,
                      style: const TextStyle(fontSize: 12),
                    ),
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
      padding: EdgeInsets.fromLTRB(16, 12, 16, bottomInset + 16),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                widget.initialLine == null
                    ? 'Add Part or Labor Line'
                    : 'Edit Service Line',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _descriptionController,
                decoration: const InputDecoration(
                  labelText: 'Part / Labor Description',
                  hintText: 'e.g. OEM Battery Replacement',
                ),
                validator: (value) {
                  if ((value ?? '').trim().isEmpty) {
                    return 'Description is required';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _partCostController,
                      decoration: const InputDecoration(labelText: 'Part Cost (Rs)'),
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      validator: _validateAmount,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextFormField(
                      controller: _serviceChargeController,
                      decoration: const InputDecoration(labelText: 'Labor Fee (Rs)'),
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      validator: _validateAmount,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _invoiceController,
                decoration: const InputDecoration(
                  labelText: 'Sales Invoice Number (Optional)',
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

class _CreateJobDirectiveSheet extends StatefulWidget {
  const _CreateJobDirectiveSheet({
    required this.jobCode,
    required this.tasksService,
  });

  final String jobCode;
  final TasksService tasksService;

  @override
  State<_CreateJobDirectiveSheet> createState() =>
      _CreateJobDirectiveSheetState();
}

class _CreateJobDirectiveSheetState extends State<_CreateJobDirectiveSheet> {
  final _formKey = GlobalKey<FormState>();
  final _titleController = TextEditingController();
  final _descController = TextEditingController();

  String _priority = 'medium';
  bool _isSubmitting = false;

  @override
  void dispose() {
    _titleController.dispose();
    _descController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    setState(() {
      _isSubmitting = true;
    });
    try {
      await widget.tasksService.createTask(
        title: _titleController.text.trim(),
        description: _descController.text.trim(),
        priority: _priority,
        jobCode: widget.jobCode,
        assignToMe: true,
      );
      if (mounted) {
        Navigator.of(context).pop(true);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppColors.warningFg,
            content: Text(e.toString().replaceFirst('Exception: ', '')),
          ),
        );
      }
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
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.fromLTRB(16, 12, 16, bottomInset + 16),
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    'Add Directive for ${widget.jobCode}',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.of(context).pop(false),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _titleController,
                decoration: const InputDecoration(
                  labelText: 'Directive Title',
                  hintText: 'e.g. Order replacement display flex cable',
                ),
                validator: (val) {
                  if ((val ?? '').trim().isEmpty) {
                    return 'Title is required';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _descController,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Instructions / Remarks',
                  hintText: 'e.g. Inspect IC power delivery rails before testing',
                ),
              ),
              const SizedBox(height: 12),
              const Text(
                'Priority',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'low', label: Text('Low')),
                  ButtonSegment(value: 'medium', label: Text('Medium')),
                  ButtonSegment(value: 'high', label: Text('High')),
                  ButtonSegment(value: 'urgent', label: Text('Urgent')),
                ],
                selected: {_priority},
                onSelectionChanged: (val) {
                  setState(() {
                    _priority = val.first;
                  });
                },
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _isSubmitting ? null : _submit,
                  icon: _isSubmitting
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.check_rounded),
                  label: Text(_isSubmitting ? 'Creating...' : 'Create Directive'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
