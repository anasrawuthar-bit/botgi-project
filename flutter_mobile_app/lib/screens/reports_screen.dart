import 'package:flutter/material.dart';

import '../models/management_models.dart';
import '../services/management_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key, required this.managementService});

  final ManagementService managementService;

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  String _preset = 'this_month';
  late Future<ReportsSummary> _reportsFuture;

  @override
  void initState() {
    super.initState();
    _reportsFuture = widget.managementService.fetchReportsSummary(
      preset: _preset,
    );
  }

  Future<void> _reload() async {
    setState(() {
      _reportsFuture = widget.managementService.fetchReportsSummary(
        preset: _preset,
      );
    });
    await _reportsFuture;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Reports')),
      body: SafeArea(
        child: FutureBuilder<ReportsSummary>(
          future: _reportsFuture,
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

            final reports = snapshot.data;
            if (reports == null) {
              return const Center(child: Text('No reports data.'));
            }

            return RefreshIndicator(
              onRefresh: _reload,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
                children: [
                  Wrap(
                    spacing: 8,
                    children: [
                      ChoiceChip(
                        label: const Text('This Month'),
                        selected: _preset == 'this_month',
                        onSelected: (_) {
                          setState(() => _preset = 'this_month');
                          _reload();
                        },
                      ),
                      ChoiceChip(
                        label: const Text('Last Month'),
                        selected: _preset == 'last_month',
                        onSelected: (_) {
                          setState(() => _preset = 'last_month');
                          _reload();
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Period: ${reports.startDate} to ${reports.endDate}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: _MetricCard(
                          title: 'Revenue',
                          value: 'Rs ${reports.overallRevenue}',
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _MetricCard(
                          title: 'Profit',
                          value: 'Rs ${reports.overallProfit}',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: _MetricCard(
                          title: 'Jobs Finished',
                          value: '${reports.jobsFinished}',
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: _MetricCard(
                          title: 'Margin',
                          value: '${reports.overallMargin}%',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  AppSurfaceCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Breakdown',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 8),
                        _RowValue(
                          label: 'Service Revenue',
                          value: 'Rs ${reports.serviceRevenue}',
                        ),
                        _RowValue(
                          label: 'Service Profit',
                          value: 'Rs ${reports.serviceProfit}',
                        ),
                        _RowValue(
                          label: 'Stock Income',
                          value: 'Rs ${reports.stockSalesIncome}',
                        ),
                        _RowValue(
                          label: 'Stock Profit',
                          value: 'Rs ${reports.stockSalesProfit}',
                        ),
                        _RowValue(
                          label: 'Vendor Revenue',
                          value: 'Rs ${reports.vendorRevenue}',
                        ),
                        _RowValue(
                          label: 'Vendor Profit',
                          value: 'Rs ${reports.vendorProfit}',
                        ),
                        _RowValue(
                          label: 'Stock Units Sold',
                          value: '${reports.stockSalesUnits}',
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  AppSurfaceCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Top Products',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 10),
                        if (reports.topProducts.isEmpty)
                          const Text('No product sales in this period.')
                        else
                          ...reports.topProducts.map(
                            (product) => Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Expanded(
                                    child: Text(
                                      '${product.name} (${product.unitsSold})',
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  const SizedBox(width: 10),
                                  Text('Rs ${product.revenue}'),
                                ],
                              ),
                            ),
                          ),
                      ],
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

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.title, required this.value});

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return AppSurfaceCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
          Text(
            value,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}

class _RowValue extends StatelessWidget {
  const _RowValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
