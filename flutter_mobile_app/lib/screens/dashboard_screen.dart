import 'package:flutter/material.dart';

import '../models/job_item.dart';
import '../models/task_model.dart';
import '../services/auth_service.dart';
import '../services/jobs_service.dart';
import '../services/management_service.dart';
import '../services/tasks_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';
import '../widgets/status_pill.dart';
import 'client_management_screen.dart';
import 'job_detail_screen.dart';
import 'pending_approvals_screen.dart';
import 'product_management_screen.dart';
import 'reports_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({
    super.key,
    required this.authService,
    required this.jobsService,
    required this.managementService,
    this.tasksService,
    this.onNavigateToTasks,
  });

  final AuthService authService;
  final JobsService jobsService;
  final ManagementService managementService;
  final TasksService? tasksService;
  final VoidCallback? onNavigateToTasks;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late Future<List<JobItem>> _jobsFuture;
  TaskMetrics _taskMetrics = TaskMetrics();

  @override
  void initState() {
    super.initState();
    _jobsFuture = widget.jobsService.fetchJobs();
    _loadTaskMetrics();
  }

  Future<void> _loadTaskMetrics() async {
    if (widget.tasksService == null) return;
    try {
      final res = await widget.tasksService!.fetchTasksWithMetrics(status: 'active');
      if (mounted) {
        setState(() {
          _taskMetrics = res.metrics;
        });
      }
    } catch (_) {}
  }

  Future<void> _refresh() async {
    setState(() {
      _jobsFuture = widget.jobsService.fetchJobs();
    });
    await Future.wait([
      _jobsFuture,
      _loadTaskMetrics(),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.authService.currentUser ?? {};
    final username = (user['username'] ?? '').toString();
    final role = (user['role'] ?? '').toString().toUpperCase();

    return SafeArea(
      child: FutureBuilder<List<JobItem>>(
        future: _jobsFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }

          if (snapshot.hasError) {
            return _ErrorBlock(
              message: snapshot.error.toString().replaceFirst(
                'Exception: ',
                '',
              ),
              onRetry: _refresh,
            );
          }

          final jobs = snapshot.data ?? <JobItem>[];
          final total = jobs.length;
          final pending = jobs
              .where(
                (j) =>
                    j.status == 'Pending' ||
                    j.status == 'Under Inspection' ||
                    j.status == 'Repairing' ||
                    j.status == 'Specialized Service',
              )
              .length;
          final closed = jobs.where((j) => j.status == 'Closed').length;
          final revenue = jobs.fold<double>(
            0,
            (sum, job) => sum + (double.tryParse(job.total) ?? 0),
          );

          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
              children: [
                Text(
                  'Welcome, $username',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 2),
                Text('Role: $role'),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: _StatCard(
                        label: 'Total Jobs',
                        value: '$total',
                        icon: Icons.receipt_long_rounded,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _StatCard(
                        label: 'Open',
                        value: '$pending',
                        icon: Icons.build_circle_outlined,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _StatCard(
                        label: 'Closed',
                        value: '$closed',
                        icon: Icons.verified_rounded,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _RevenueCard(amount: revenue),
                const SizedBox(height: 12),
                _DirectivesSummaryCard(
                  metrics: _taskMetrics,
                  onTap: widget.onNavigateToTasks,
                ),
                const SizedBox(height: 16),
                Text(
                  'Operations',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: _ModuleTile(
                        icon: Icons.inventory_2_outlined,
                        title: 'Product Management',
                        onTap: () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => ProductManagementScreen(
                                managementService: widget.managementService,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _ModuleTile(
                        icon: Icons.pending_actions_outlined,
                        title: 'Pending Approvals',
                        onTap: () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => PendingApprovalsScreen(
                                managementService: widget.managementService,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: _ModuleTile(
                        icon: Icons.groups_outlined,
                        title: 'Client Management',
                        onTap: () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => ClientManagementScreen(
                                managementService: widget.managementService,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _ModuleTile(
                        icon: Icons.analytics_outlined,
                        title: 'Reports',
                        onTap: () {
                          Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => ReportsScreen(
                                managementService: widget.managementService,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'Recent Jobs',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    TextButton.icon(
                      onPressed: _refresh,
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Refresh'),
                    ),
                  ],
                ),
                if (jobs.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 18),
                    child: Center(child: Text('No jobs found.')),
                  )
                else
                  ...jobs
                      .take(6)
                      .map(
                        (job) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Card(
                            child: ListTile(
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 6,
                              ),
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
                                  await _refresh();
                                }
                              },
                              title: Text(job.jobCode),
                              subtitle: Text(
                                '${job.customerName} - ${job.device}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              trailing: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  StatusPill(status: job.status, compact: true),
                                  const SizedBox(height: 4),
                                  Text('Rs ${job.total}'),
                                ],
                              ),
                            ),
                          ),
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

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return AppSurfaceCard(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20),
          const SizedBox(height: 10),
          Text(
            value,
            style: Theme.of(
              context,
            ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 2),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

class _ModuleTile extends StatelessWidget {
  const _ModuleTile({
    required this.icon,
    required this.title,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(18),
      child: AppSurfaceCard(
        padding: const EdgeInsets.fromLTRB(12, 14, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 22),
            const SizedBox(height: 10),
            Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}

class _RevenueCard extends StatelessWidget {
  const _RevenueCard({required this.amount});

  final double amount;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [AppColors.primary, AppColors.accent],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 14),
        child: Row(
          children: [
            const Icon(Icons.currency_rupee_rounded, color: Colors.white),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Visible Revenue',
                    style: TextStyle(color: Colors.white70),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Rs ${amount.toStringAsFixed(2)}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorBlock extends StatelessWidget {
  const _ErrorBlock({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.warningFg),
            ),
            const SizedBox(height: 10),
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _DirectivesSummaryCard extends StatelessWidget {
  const _DirectivesSummaryCard({
    required this.metrics,
    this.onTap,
  });

  final TaskMetrics metrics;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: metrics.urgent > 0 ? const Color(0xFFFCA5A5) : Colors.grey.shade200,
            width: metrics.urgent > 0 ? 1.5 : 1,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.03),
              blurRadius: 6,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: metrics.urgent > 0 ? const Color(0xFFFEF2F2) : const Color(0xFFEFF6FF),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                metrics.urgent > 0 ? Icons.bolt_rounded : Icons.assignment_outlined,
                color: metrics.urgent > 0 ? const Color(0xFFDC2626) : const Color(0xFF2563EB),
                size: 24,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Text(
                        'Directives & Tasks',
                        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
                      ),
                      if (metrics.urgent > 0) ...[
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1.5),
                          decoration: BoxDecoration(
                            color: const Color(0xFFDC2626),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Text(
                            '${metrics.urgent} Urgent',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 10,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${metrics.active} active tasks • ${metrics.inProgress} in progress',
                    style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                  ),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios_rounded, size: 14, color: Colors.grey),
          ],
        ),
      ),
    );
  }
}

