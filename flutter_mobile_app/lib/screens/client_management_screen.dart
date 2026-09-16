import 'package:flutter/material.dart';

import '../models/management_models.dart';
import '../services/management_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class ClientManagementScreen extends StatefulWidget {
  const ClientManagementScreen({super.key, required this.managementService});

  final ManagementService managementService;

  @override
  State<ClientManagementScreen> createState() => _ClientManagementScreenState();
}

class _ClientManagementScreenState extends State<ClientManagementScreen> {
  final TextEditingController _searchController = TextEditingController();
  late Future<ClientListResponse> _clientsFuture;

  @override
  void initState() {
    super.initState();
    _clientsFuture = widget.managementService.fetchClients();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _clientsFuture = widget.managementService.fetchClients(
        query: _searchController.text,
      );
    });
    await _clientsFuture;
  }

  Future<void> _openEditor({
    ClientRecord? client,
    required bool canEdit,
  }) async {
    if (!canEdit) {
      return;
    }
    final input = await showModalBottomSheet<_ClientInput>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _ClientEditorSheet(initial: client),
    );
    if (input == null) {
      return;
    }

    try {
      final message = client == null
          ? await widget.managementService.createClient(
              name: input.name,
              phone: input.phone,
              email: input.email,
              companyName: input.companyName,
              address: input.address,
              notes: input.notes,
              isActive: input.isActive,
            )
          : await widget.managementService.updateClient(
              clientId: client.id,
              name: input.name,
              phone: input.phone,
              email: input.email,
              companyName: input.companyName,
              address: input.address,
              notes: input.notes,
              isActive: input.isActive,
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
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Client Management')),
      body: SafeArea(
        child: FutureBuilder<ClientListResponse>(
          future: _clientsFuture,
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

            final data = snapshot.data ?? ClientListResponse(canEdit: false, clients: const []);
            return RefreshIndicator(
              onRefresh: _reload,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
                children: [
                  AppSurfaceCard(
                    child: Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _searchController,
                            decoration: const InputDecoration(
                              hintText: 'Search name / phone / company',
                              prefixIcon: Icon(Icons.search),
                            ),
                            onSubmitted: (_) => _reload(),
                          ),
                        ),
                        const SizedBox(width: 8),
                        IconButton(
                          tooltip: 'Search',
                          onPressed: _reload,
                          icon: const Icon(Icons.arrow_forward_rounded),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '${data.clients.length} clients',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  if (data.clients.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Center(child: Text('No clients found.')),
                    )
                  else
                    ...data.clients.map(
                      (client) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppSurfaceCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      client.name,
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                        fontSize: 16,
                                      ),
                                    ),
                                  ),
                                  if (data.canEdit)
                                    TextButton.icon(
                                      onPressed: () => _openEditor(
                                        client: client,
                                        canEdit: data.canEdit,
                                      ),
                                      icon: const Icon(Icons.edit_outlined, size: 18),
                                      label: const Text('Edit'),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              Text('Phone: ${client.phone}'),
                              if (client.email.isNotEmpty) Text('Email: ${client.email}'),
                              if (client.companyName.isNotEmpty) Text('Company: ${client.companyName}'),
                              Text('Status: ${client.isActive ? 'Active' : 'Inactive'}'),
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
      floatingActionButton: FutureBuilder<ClientListResponse>(
        future: _clientsFuture,
        builder: (context, snapshot) {
          final canEdit = snapshot.data?.canEdit ?? false;
          if (!canEdit) {
            return const SizedBox.shrink();
          }
          return FloatingActionButton.extended(
            onPressed: () => _openEditor(canEdit: true),
            icon: const Icon(Icons.add),
            label: const Text('Add Client'),
          );
        },
      ),
    );
  }
}

class _ClientInput {
  const _ClientInput({
    required this.name,
    required this.phone,
    required this.email,
    required this.companyName,
    required this.address,
    required this.notes,
    required this.isActive,
  });

  final String name;
  final String phone;
  final String email;
  final String companyName;
  final String address;
  final String notes;
  final bool isActive;
}

class _ClientEditorSheet extends StatefulWidget {
  const _ClientEditorSheet({this.initial});

  final ClientRecord? initial;

  @override
  State<_ClientEditorSheet> createState() => _ClientEditorSheetState();
}

class _ClientEditorSheetState extends State<_ClientEditorSheet> {
  final _formKey = GlobalKey<FormState>();

  late final TextEditingController _nameController;
  late final TextEditingController _phoneController;
  late final TextEditingController _emailController;
  late final TextEditingController _companyController;
  late final TextEditingController _addressController;
  late final TextEditingController _notesController;
  bool _isActive = true;

  @override
  void initState() {
    super.initState();
    final c = widget.initial;
    _nameController = TextEditingController(text: c?.name ?? '');
    _phoneController = TextEditingController(text: c?.phone ?? '');
    _emailController = TextEditingController(text: c?.email ?? '');
    _companyController = TextEditingController(text: c?.companyName ?? '');
    _addressController = TextEditingController(text: c?.address ?? '');
    _notesController = TextEditingController(text: c?.notes ?? '');
    _isActive = c?.isActive ?? true;
  }

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    _emailController.dispose();
    _companyController.dispose();
    _addressController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    Navigator.of(context).pop(
      _ClientInput(
        name: _nameController.text.trim(),
        phone: _phoneController.text.trim(),
        email: _emailController.text.trim(),
        companyName: _companyController.text.trim(),
        address: _addressController.text.trim(),
        notes: _notesController.text.trim(),
        isActive: _isActive,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 10, 16, bottomInset + 16),
      child: SingleChildScrollView(
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                widget.initial == null ? 'Add Client' : 'Edit Client',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _nameController,
                decoration: const InputDecoration(labelText: 'Name'),
                validator: (value) => (value ?? '').trim().isEmpty ? 'Required' : null,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _phoneController,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(labelText: 'Phone'),
                validator: (value) => (value ?? '').trim().isEmpty ? 'Required' : null,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _emailController,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email'),
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _companyController,
                decoration: const InputDecoration(labelText: 'Company Name'),
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _addressController,
                decoration: const InputDecoration(labelText: 'Address'),
                maxLines: 2,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _notesController,
                decoration: const InputDecoration(labelText: 'Notes'),
                maxLines: 2,
              ),
              const SizedBox(height: 8),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _isActive,
                onChanged: (value) => setState(() => _isActive = value),
                title: const Text('Active'),
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.save_outlined),
                  label: const Text('Save'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
