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
  });

  final AuthService authService;
  final JobsService jobsService;

  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  late Future<List<JobItem>> _jobsFuture;
  final TextEditingController _searchController = TextEditingController();
  String _statusFilter = 'ALL';

  @override
  void initState() {
    super.initState();
    _jobsFuture = widget.jobsService.fetchJobs();
    _searchController.addListener(() {
      setState(() {});
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadJobs() async {
    setState(() {
      _jobsFuture = widget.jobsService.fetchJobs();
    });
    await _jobsFuture;
  }

  @override
  Widget build(BuildContext context) {
    final currentUser = widget.authService.currentUser ?? {};
    final username = (currentUser['username'] ?? '').toString();
    final role = (currentUser['role'] ?? '').toString();

    return SafeArea(
      child: FutureBuilder<List<JobItem>>(
        future: _jobsFuture,
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
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _loadJobs,
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
            );
          }

          final jobs = snapshot.data ?? <JobItem>[];
          final filteredJobs = jobs.where(_filterJob).toList(growable: false);

          return RefreshIndicator(
            onRefresh: _loadJobs,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
              children: [
                Text('Jobs', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 2),
                Text('Signed in as $username (${role.toUpperCase()})'),
                const SizedBox(height: 12),
                AppSurfaceCard(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    children: [
                      TextField(
                        controller: _searchController,
                        decoration: const InputDecoration(
                          hintText: 'Search by job code or customer',
                          prefixIcon: Icon(Icons.search),
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            _FilterChip(
                              label: 'All',
                              selected: _statusFilter == 'ALL',
                              onTap: () =>
                                  setState(() => _statusFilter = 'ALL'),
                            ),
                            _FilterChip(
                              label: 'Pending',
                              selected: _statusFilter == 'Pending',
                              onTap: () =>
                                  setState(() => _statusFilter = 'Pending'),
                            ),
                            _FilterChip(
                              label: 'Repairing',
                              selected: _statusFilter == 'Repairing',
                              onTap: () =>
                                  setState(() => _statusFilter = 'Repairing'),
                            ),
                            _FilterChip(
                              label: 'Completed',
                              selected: _statusFilter == 'Completed',
                              onTap: () =>
                                  setState(() => _statusFilter = 'Completed'),
                            ),
                            _FilterChip(
                              label: 'Closed',
                              selected: _statusFilter == 'Closed',
                              onTap: () =>
                                  setState(() => _statusFilter = 'Closed'),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (filteredJobs.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(
                      child: Text('No jobs found for this filter.'),
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
                        child: Card(
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Row(
                                      children: [
                                        Text(
                                          job.jobCode,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w700,
                                          ),
                                        ),
                                        if (job.priority.isNotEmpty && job.priority.toLowerCase() != 'medium') ...[
                                          const SizedBox(width: 8),
                                          PriorityBadge(
                                            priority: job.priority,
                                            compact: true,
                                          ),
                                        ],
                                      ],
                                    ),
                                    StatusPill(
                                      status: job.status,
                                      compact: true,
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Text(job.customerName),
                                const SizedBox(height: 4),
                                Text(
                                  job.device,
                                  style: Theme.of(context).textTheme.bodySmall,
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
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      'Updated: ${job.updatedAt}',
                                      style: Theme.of(
                                        context,
                                      ).textTheme.bodySmall,
                                    ),
                                    Text(
                                      'Rs ${job.total}',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
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
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  bool _filterJob(JobItem job) {
    final q = _searchController.text.trim().toLowerCase();
    final matchesText =
        q.isEmpty ||
        job.jobCode.toLowerCase().contains(q) ||
        job.customerName.toLowerCase().contains(q);

    final matchesStatus = _statusFilter == 'ALL' || job.status == _statusFilter;
    return matchesText && matchesStatus;
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
          ),
        ),
      ),
    );
  }
}
