import 'package:flutter/material.dart';

import '../models/job_item.dart';
import '../services/auth_service.dart';
import '../services/jobs_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/priority_badge.dart';
import '../widgets/status_pill.dart';
import 'job_detail_screen.dart';

class JobsScreen extends StatefulWidget {
  const JobsScreen({
    super.key,
    required this.authService,
    required this.jobsService,
    this.initialScope,
    this.initialPreset,
  });

  final AuthService authService;
  final JobsService jobsService;
  final String? initialScope;
  final String? initialPreset;

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> with AutomaticKeepAliveClientMixin<JobsScreen> {
  final TextEditingController _searchController = TextEditingController();

  late String _scope; // 'active', 'history', 'all'
  late String _preset; // 'all', 'this_month', 'last_month', 'custom'
  String _customMonth = '';
  String _customMonthLabel = '';
  String _statusFilter = 'ALL';

  JobsResponse? _cachedResponse;
  bool _isSyncing = false;
  String? _errorMessage;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    final role = (widget.authService.currentUser?['role'] ?? '').toString().toLowerCase();
    final isTech = role == 'technician';

    _scope = widget.initialScope ?? (isTech ? 'active' : 'all');
    _preset = widget.initialPreset ?? 'all';

    // Synchronous instant cache lookup (0ms perceived latency)
    _cachedResponse = widget.jobsService.getCachedJobsWithSummary(
      scope: _scope == 'all' ? null : _scope,
      preset: _preset == 'custom' ? null : (_preset == 'all' ? null : _preset),
      reportMonth: _preset == 'custom' ? _customMonth : null,
      limit: 300,
    );

    // Silent background sync
    _loadJobs(silent: _cachedResponse != null);

    _searchController.addListener(() {
      setState(() {});
    });
  }

  @override
  void didUpdateWidget(JobsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if ((widget.initialScope != null && widget.initialScope != _scope) ||
        (widget.initialPreset != null && widget.initialPreset != _preset)) {
      applyExternalFilters(
        scope: widget.initialScope,
        preset: widget.initialPreset,
      );
    }
  }

  void applyExternalFilters({String? scope, String? preset}) {
    if (!mounted) return;
    final newScope = scope ?? _scope;
    final newPreset = preset ?? _preset;
    if (_scope == newScope && _preset == newPreset) return;

    setState(() {
      _scope = newScope;
      _preset = newPreset;
      _statusFilter = 'ALL';
      final cached = widget.jobsService.getCachedJobsWithSummary(
        scope: _scope == 'all' ? null : _scope,
        preset: _preset == 'custom' ? null : (_preset == 'all' ? null : _preset),
        reportMonth: _preset == 'custom' ? _customMonth : null,
        limit: 300,
      );
      if (cached != null) {
        _cachedResponse = cached;
      }
    });
    _loadJobs(silent: _cachedResponse != null);
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadJobs({bool silent = false}) async {
    if (!silent && _cachedResponse == null) {
      setState(() {
        _isSyncing = true;
        _errorMessage = null;
      });
    } else {
      if (mounted) {
        setState(() {
          _isSyncing = true;
        });
      }
    }

    try {
      final res = await widget.jobsService.fetchJobsWithSummary(
        scope: _scope == 'all' ? null : _scope,
        preset: _preset == 'custom' ? null : (_preset == 'all' ? null : _preset),
        reportMonth: _preset == 'custom' ? _customMonth : null,
        limit: 300,
      );
      if (!mounted) return;
      setState(() {
        _cachedResponse = res;
        _isSyncing = false;
        _errorMessage = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _isSyncing = false;
        if (_cachedResponse == null) {
          _errorMessage = e.toString().replaceFirst('Exception: ', '');
        }
      });
    }
  }

  void _setScope(String scope) {
    if (_scope == scope) return;
    setState(() {
      _scope = scope;
      _statusFilter = 'ALL';
      final cached = widget.jobsService.getCachedJobsWithSummary(
        scope: _scope == 'all' ? null : _scope,
        preset: _preset == 'custom' ? null : (_preset == 'all' ? null : _preset),
        reportMonth: _preset == 'custom' ? _customMonth : null,
        limit: 300,
      );
      if (cached != null) {
        _cachedResponse = cached;
      }
    });
    _loadJobs(silent: _cachedResponse != null);
  }

  void _setPreset(String preset, {String? customMonth, String? customLabel}) {
    setState(() {
      _preset = preset;
      if (customMonth != null) {
        _customMonth = customMonth;
        _customMonthLabel = customLabel ?? customMonth;
      }
      final cached = widget.jobsService.getCachedJobsWithSummary(
        scope: _scope == 'all' ? null : _scope,
        preset: _preset == 'custom' ? null : (_preset == 'all' ? null : _preset),
        reportMonth: _preset == 'custom' ? _customMonth : null,
        limit: 300,
      );
      if (cached != null) {
        _cachedResponse = cached;
      }
    });
    _loadJobs(silent: _cachedResponse != null);
  }

  static String _monthName(int month) {
    const names = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'
    ];
    if (month >= 1 && month <= 12) {
      return names[month - 1];
    }
    return '';
  }

  static String _formatMonthYear(DateTime date) {
    return '${_monthName(date.month)} ${date.year}';
  }

  List<Map<String, String>> _getPastMonths() {
    final now = DateTime.now();
    final list = <Map<String, String>>[];
    for (int i = 0; i < 18; i++) {
      final d = DateTime(now.year, now.month - i, 1);
      final key = '${d.year}-${d.month.toString().padLeft(2, '0')}';
      final label = _formatMonthYear(d);
      list.add({'key': key, 'label': label});
    }
    return list;
  }

  Future<void> _openMonthPicker() async {
    final months = _getPastMonths();
    final selected = await showModalBottomSheet<Map<String, String>>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 16, 14, 8),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Select History Month',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => Navigator.of(context).pop(),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView.builder(
                  shrinkWrap: true,
                  itemCount: months.length,
                  itemBuilder: (context, index) {
                    final m = months[index];
                    final isCurrent = _preset == 'custom' && _customMonth == m['key'];
                    return ListTile(
                      title: Text(
                        m['label']!,
                        style: TextStyle(
                          fontWeight: isCurrent ? FontWeight.w700 : FontWeight.w500,
                          color: isCurrent ? AppColors.primary : AppColors.ink900,
                        ),
                      ),
                      trailing: isCurrent
                          ? const Icon(Icons.check_circle_rounded, color: AppColors.primary)
                          : null,
                      onTap: () => Navigator.of(context).pop(m),
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );

    if (selected != null) {
      _setPreset('custom', customMonth: selected['key'], customLabel: selected['label']);
    }
  }

  String get _currentPeriodLabel {
    final now = DateTime.now();
    if (_preset == 'this_month') {
      return 'This Month (${_monthName(now.month)} ${now.year})';
    } else if (_preset == 'last_month') {
      final lastMonth = DateTime(now.year, now.month - 1, 1);
      return 'Last Month (${_monthName(lastMonth.month)} ${lastMonth.year})';
    } else if (_preset == 'custom' && _customMonthLabel.isNotEmpty) {
      return _customMonthLabel;
    }
    return 'All Time History';
  }

  List<String> get _currentStatusFilters {
    if (_scope == 'active') {
      return const ['ALL', 'Pending', 'Under Inspection', 'Repairing', 'Specialized Service'];
    } else if (_scope == 'history') {
      return const ['ALL', 'Completed', 'Closed', 'Ready for Pickup'];
    } else {
      return const ['ALL', 'Pending', 'Repairing', 'Completed', 'Closed'];
    }
  }

  Widget _buildColdSkeleton(BuildContext context, String username, String role) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Jobs & History', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 2),
                Text('Signed in as $username ($role)'),
              ],
            ),
          ],
        ),
        const SizedBox(height: 14),
        Container(
          height: 44,
          decoration: BoxDecoration(
            color: const Color(0xFFF1F5F9),
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        const SizedBox(height: 16),
        ...List.generate(
          4,
          (index) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: AppSurfaceCard(
              child: SizedBox(
                height: 80,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Container(
                      height: 16,
                      width: 120,
                      decoration: BoxDecoration(
                        color: Colors.grey.shade200,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      height: 12,
                      width: 200,
                      decoration: BoxDecoration(
                        color: Colors.grey.shade100,
                        borderRadius: BorderRadius.circular(4),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final currentUser = widget.authService.currentUser ?? {};
    final username = (currentUser['username'] ?? '').toString();
    final roleRaw = (currentUser['role'] ?? '').toString().toLowerCase();
    final isTechnician = roleRaw == 'technician';
    final role = (currentUser['role'] ?? '').toString().toUpperCase();

    if (_cachedResponse == null && _isSyncing) {
      return SafeArea(child: _buildColdSkeleton(context, username, role));
    }

    if (_cachedResponse == null && _errorMessage != null) {
      return SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  _errorMessage!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: AppColors.warningFg),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => _loadJobs(),
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final response = _cachedResponse ?? const JobsResponse(jobs: [], summary: JobsSummary());
    final jobs = response.jobs;
    final summary = response.summary;
    final filteredJobs = jobs.where(_filterJob).toList(growable: false);

    final showMonthBar = _scope == 'history' || _scope == 'all';
    final showSummaryCard = _scope == 'history' || _preset != 'all';

    return SafeArea(
      child: Column(
        children: [
          if (_isSyncing)
            const LinearProgressIndicator(
              minHeight: 2,
              backgroundColor: Colors.transparent,
              valueColor: AlwaysStoppedAnimation<Color>(AppColors.primary),
            ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () => _loadJobs(silent: true),
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Jobs & History', style: Theme.of(context).textTheme.headlineSmall),
                        const SizedBox(height: 2),
                        Text('Signed in as $username ($role)'),
                      ],
                    ),
                    IconButton(
                      tooltip: 'Refresh',
                      onPressed: _loadJobs,
                      icon: const Icon(Icons.refresh_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Scope Segmented Switcher (Active Jobs / History / All)
                Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFFF1F5F9),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  padding: const EdgeInsets.all(4),
                  child: Row(
                    children: [
                      _ScopeButton(
                        label: 'Active Jobs',
                        icon: Icons.handyman_outlined,
                        isSelected: _scope == 'active',
                        onTap: () => _setScope('active'),
                      ),
                      _ScopeButton(
                        label: 'Job History',
                        icon: Icons.history_rounded,
                        isSelected: _scope == 'history',
                        onTap: () => _setScope('history'),
                      ),
                      _ScopeButton(
                        label: 'All',
                        icon: Icons.list_alt_rounded,
                        isSelected: _scope == 'all',
                        onTap: () => _setScope('all'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),

                // Month filter bar (When viewing History or All)
                if (showMonthBar) ...[
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(
                      children: [
                        _FilterChip(
                          label: 'All Time',
                          selected: _preset == 'all',
                          onTap: () => _setPreset('all'),
                        ),
                        const SizedBox(width: 8),
                        _FilterChip(
                          label: 'This Month',
                          selected: _preset == 'this_month',
                          onTap: () => _setPreset('this_month'),
                        ),
                        const SizedBox(width: 8),
                        _FilterChip(
                          label: 'Last Month',
                          selected: _preset == 'last_month',
                          onTap: () => _setPreset('last_month'),
                        ),
                        const SizedBox(width: 8),
                        InkWell(
                          onTap: _openMonthPicker,
                          borderRadius: BorderRadius.circular(999),
                          child: Container(
                            decoration: BoxDecoration(
                              color: _preset == 'custom'
                                  ? AppColors.primary
                                  : const Color(0xFFE9EEF4),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.calendar_month_outlined,
                                  size: 15,
                                  color: _preset == 'custom' ? Colors.white : AppColors.ink700,
                                ),
                                const SizedBox(width: 4),
                                Text(
                                  _preset == 'custom' ? _customMonthLabel : 'Pick Month...',
                                  style: TextStyle(
                                    color: _preset == 'custom' ? Colors.white : AppColors.ink700,
                                    fontWeight: FontWeight.w600,
                                    fontSize: 13,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                ],

                // History / Month Summary Card
                if (showSummaryCard)
                  _HistorySummaryCard(
                    periodLabel: _currentPeriodLabel,
                    summary: summary,
                    isTechnician: isTechnician,
                  ),

                // Search & Status Filters Card
                AppSurfaceCard(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      TextField(
                        controller: _searchController,
                        decoration: InputDecoration(
                          hintText: 'Search by job code, device, or customer',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: _searchController.text.isNotEmpty
                              ? IconButton(
                                  icon: const Icon(Icons.clear, size: 18),
                                  onPressed: () => _searchController.clear(),
                                )
                              : null,
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: _currentStatusFilters.map((st) {
                            return _FilterChip(
                              label: st == 'ALL' ? 'All Status' : st,
                              selected: _statusFilter == st,
                              onTap: () => setState(() => _statusFilter = st),
                            );
                          }).toList(),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),

                // Results count
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Showing ${filteredJobs.length} of ${jobs.length} jobs',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                    ),
                    if (_statusFilter != 'ALL' || _searchController.text.isNotEmpty)
                      GestureDetector(
                        onTap: () {
                          setState(() {
                            _statusFilter = 'ALL';
                            _searchController.clear();
                          });
                        },
                        child: const Text(
                          'Clear Filters',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppColors.primary,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 8),

                if (filteredJobs.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 36),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            _scope == 'history'
                                ? Icons.history_toggle_off_rounded
                                : Icons.inventory_2_outlined,
                            size: 48,
                            color: Colors.grey.shade400,
                          ),
                          const SizedBox(height: 10),
                          Text(
                            _scope == 'history'
                                ? 'No completed jobs found for $_currentPeriodLabel.'
                                : 'No jobs found matching the selected filters.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.grey.shade600),
                          ),
                        ],
                      ),
                    ),
                  )
                else
                  ...filteredJobs.map(
                    (job) => Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(18),
                        onTap: () async {
                          await Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => JobDetailScreen(
                                jobCode: job.jobCode,
                                jobsService: widget.jobsService,
                              ),
                            ),
                          );
                          if (mounted) {
                            await _loadJobs();
                          }
                        },
                        child: AppSurfaceCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(
                                    child: Row(
                                      children: [
                                        Text(
                                          job.jobCode,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                            fontSize: 16,
                                          ),
                                        ),
                                        if (job.priority.isNotEmpty &&
                                            job.priority.toLowerCase() != 'medium') ...[
                                          const SizedBox(width: 8),
                                          PriorityBadge(
                                            priority: job.priority,
                                            compact: true,
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                  StatusPill(
                                    status: job.status,
                                    compact: true,
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  const Icon(Icons.person_outline, size: 14, color: AppColors.ink500),
                                  const SizedBox(width: 4),
                                  Expanded(
                                    child: Text(
                                      job.customerName,
                                      style: const TextStyle(fontWeight: FontWeight.w600),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Row(
                                children: [
                                  const Icon(Icons.devices_other, size: 14, color: AppColors.ink500),
                                  const SizedBox(width: 4),
                                  Expanded(
                                    child: Text(
                                      job.device,
                                      style: Theme.of(context).textTheme.bodySmall,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              if (job.dueDate.isNotEmpty) ...[
                                Row(
                                  children: [
                                    const Icon(Icons.schedule, size: 12, color: Colors.blueGrey),
                                    const SizedBox(width: 4),
                                    Text(
                                      'Due: ${job.dueDate}',
                                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                            fontWeight: FontWeight.w600,
                                          ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 4),
                              ],
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    'Updated: ${job.updatedAt}',
                                    style: Theme.of(context).textTheme.bodySmall,
                                  ),
                                  Text(
                                    'Rs ${job.total}',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.primary,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}

  bool _filterJob(JobItem job) {
    final q = _searchController.text.trim().toLowerCase();
    final matchesText = q.isEmpty ||
        job.jobCode.toLowerCase().contains(q) ||
        job.customerName.toLowerCase().contains(q) ||
        job.device.toLowerCase().contains(q);

    final matchesStatus = _statusFilter == 'ALL' ||
        job.status.toLowerCase() == _statusFilter.toLowerCase();

    return matchesText && matchesStatus;
  }
}

class _ScopeButton extends StatelessWidget {
  const _ScopeButton({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            color: isSelected ? Colors.white : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            boxShadow: isSelected
                ? [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.06),
                      blurRadius: 4,
                      offset: const Offset(0, 1),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                icon,
                size: 15,
                color: isSelected ? AppColors.primary : AppColors.ink500,
              ),
              const SizedBox(width: 5),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  color: isSelected ? AppColors.primary : AppColors.ink700,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HistorySummaryCard extends StatelessWidget {
  const _HistorySummaryCard({
    required this.periodLabel,
    required this.summary,
    required this.isTechnician,
  });

  final String periodLabel;
  final JobsSummary summary;
  final bool isTechnician;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [
            Color(0xFF0F172A),
            Color(0xFF1E293B),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.history_edu_rounded, color: Colors.amber, size: 20),
                  const SizedBox(width: 8),
                  Text(
                    periodLabel,
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '${summary.count} Jobs',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Parts Logged',
                        style: TextStyle(color: Colors.white70, fontSize: 11),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'Rs ${summary.partsTotal}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(width: 1, height: 26, color: Colors.white24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Labor Logged',
                        style: TextStyle(color: Colors.white70, fontSize: 11),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'Rs ${summary.serviceTotal}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(width: 1, height: 26, color: Colors.white24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Total Billed',
                        style: TextStyle(color: Colors.amber, fontSize: 11, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'Rs ${summary.grandTotal}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                          fontSize: 14,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(999),
      child: Ink(
        decoration: BoxDecoration(
          color: selected ? AppColors.primary : const Color(0xFFE9EEF4),
          borderRadius: BorderRadius.circular(999),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? Colors.white : AppColors.ink700,
            fontWeight: FontWeight.w600,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}
