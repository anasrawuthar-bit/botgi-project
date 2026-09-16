import 'package:flutter/material.dart';

import '../models/management_models.dart';
import '../services/management_service.dart';
import '../theme/app_colors.dart';
import '../widgets/app_surface_card.dart';

class ProductManagementScreen extends StatefulWidget {
  const ProductManagementScreen({super.key, required this.managementService});

  final ManagementService managementService;

  @override
  State<ProductManagementScreen> createState() => _ProductManagementScreenState();
}

class _ProductManagementScreenState extends State<ProductManagementScreen> {
  final TextEditingController _searchController = TextEditingController();
  late Future<ProductListResponse> _productsFuture;

  @override
  void initState() {
    super.initState();
    _productsFuture = widget.managementService.fetchProducts();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _productsFuture = widget.managementService.fetchProducts(
        query: _searchController.text,
      );
    });
    await _productsFuture;
  }

  Future<void> _openEditor({
    ProductRecord? product,
    required bool canEdit,
  }) async {
    if (!canEdit) {
      return;
    }
    final input = await showModalBottomSheet<_ProductInput>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _ProductEditorSheet(initial: product),
    );
    if (input == null) {
      return;
    }

    try {
      final message = product == null
          ? await widget.managementService.createProduct(
              name: input.name,
              sku: input.sku,
              category: input.category,
              brand: input.brand,
              unitPrice: input.unitPrice,
              costPrice: input.costPrice,
              stockQuantity: input.stockQuantity,
              description: input.description,
              isActive: input.isActive,
            )
          : await widget.managementService.updateProduct(
              productId: product.id,
              name: input.name,
              sku: input.sku,
              category: input.category,
              brand: input.brand,
              unitPrice: input.unitPrice,
              costPrice: input.costPrice,
              stockQuantity: input.stockQuantity,
              description: input.description,
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
      appBar: AppBar(title: const Text('Product Management')),
      body: SafeArea(
        child: FutureBuilder<ProductListResponse>(
          future: _productsFuture,
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

            final data = snapshot.data ?? ProductListResponse(canEdit: false, products: const []);
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
                              hintText: 'Search product / SKU / brand',
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
                    '${data.products.length} products',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  if (data.products.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 24),
                      child: Center(child: Text('No products found.')),
                    )
                  else
                    ...data.products.map(
                      (product) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: AppSurfaceCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      product.name,
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                        fontSize: 16,
                                      ),
                                    ),
                                  ),
                                  if (data.canEdit)
                                    TextButton.icon(
                                      onPressed: () => _openEditor(
                                        product: product,
                                        canEdit: data.canEdit,
                                      ),
                                      icon: const Icon(Icons.edit_outlined, size: 18),
                                      label: const Text('Edit'),
                                    ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              Text('SKU: ${product.sku.isEmpty ? '-' : product.sku}'),
                              Text('Category: ${product.category.isEmpty ? '-' : product.category}'),
                              Text('Brand: ${product.brand.isEmpty ? '-' : product.brand}'),
                              const SizedBox(height: 6),
                              Text('Unit Price: Rs ${product.unitPrice}'),
                              Text('Cost Price: Rs ${product.costPrice}'),
                              Text('Stock: ${product.stockQuantity}'),
                              Text('Status: ${product.isActive ? 'Active' : 'Inactive'}'),
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
      floatingActionButton: FutureBuilder<ProductListResponse>(
        future: _productsFuture,
        builder: (context, snapshot) {
          final canEdit = snapshot.data?.canEdit ?? false;
          if (!canEdit) {
            return const SizedBox.shrink();
          }
          return FloatingActionButton.extended(
            onPressed: () => _openEditor(canEdit: true),
            icon: const Icon(Icons.add),
            label: const Text('Add Product'),
          );
        },
      ),
    );
  }
}

class _ProductInput {
  const _ProductInput({
    required this.name,
    required this.sku,
    required this.category,
    required this.brand,
    required this.unitPrice,
    required this.costPrice,
    required this.stockQuantity,
    required this.description,
    required this.isActive,
  });

  final String name;
  final String sku;
  final String category;
  final String brand;
  final String unitPrice;
  final String costPrice;
  final int stockQuantity;
  final String description;
  final bool isActive;
}

class _ProductEditorSheet extends StatefulWidget {
  const _ProductEditorSheet({this.initial});

  final ProductRecord? initial;

  @override
  State<_ProductEditorSheet> createState() => _ProductEditorSheetState();
}

class _ProductEditorSheetState extends State<_ProductEditorSheet> {
  final _formKey = GlobalKey<FormState>();

  late final TextEditingController _nameController;
  late final TextEditingController _skuController;
  late final TextEditingController _categoryController;
  late final TextEditingController _brandController;
  late final TextEditingController _unitPriceController;
  late final TextEditingController _costPriceController;
  late final TextEditingController _stockController;
  late final TextEditingController _descriptionController;
  bool _isActive = true;

  @override
  void initState() {
    super.initState();
    final p = widget.initial;
    _nameController = TextEditingController(text: p?.name ?? '');
    _skuController = TextEditingController(text: p?.sku ?? '');
    _categoryController = TextEditingController(text: p?.category ?? '');
    _brandController = TextEditingController(text: p?.brand ?? '');
    _unitPriceController = TextEditingController(text: p?.unitPrice ?? '0');
    _costPriceController = TextEditingController(text: p?.costPrice ?? '0');
    _stockController = TextEditingController(
      text: p == null ? '0' : '${p.stockQuantity}',
    );
    _descriptionController = TextEditingController(text: p?.description ?? '');
    _isActive = p?.isActive ?? true;
  }

  @override
  void dispose() {
    _nameController.dispose();
    _skuController.dispose();
    _categoryController.dispose();
    _brandController.dispose();
    _unitPriceController.dispose();
    _costPriceController.dispose();
    _stockController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  String? _validateMoney(String? value) {
    final text = (value ?? '').trim();
    if (text.isEmpty) {
      return 'Required';
    }
    if (num.tryParse(text) == null) {
      return 'Invalid amount';
    }
    return null;
  }

  String? _validateStock(String? value) {
    final text = (value ?? '').trim();
    if (text.isEmpty) {
      return 'Required';
    }
    final parsed = int.tryParse(text);
    if (parsed == null || parsed < 0) {
      return 'Invalid stock';
    }
    return null;
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    Navigator.of(context).pop(
      _ProductInput(
        name: _nameController.text.trim(),
        sku: _skuController.text.trim(),
        category: _categoryController.text.trim(),
        brand: _brandController.text.trim(),
        unitPrice: _unitPriceController.text.trim(),
        costPrice: _costPriceController.text.trim(),
        stockQuantity: int.parse(_stockController.text.trim()),
        description: _descriptionController.text.trim(),
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
                widget.initial == null ? 'Add Product' : 'Edit Product',
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
                controller: _skuController,
                decoration: const InputDecoration(labelText: 'SKU'),
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _categoryController,
                decoration: const InputDecoration(labelText: 'Category'),
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _brandController,
                decoration: const InputDecoration(labelText: 'Brand'),
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _unitPriceController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Unit Price'),
                validator: _validateMoney,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _costPriceController,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Cost Price'),
                validator: _validateMoney,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _stockController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Stock Quantity'),
                validator: _validateStock,
              ),
              const SizedBox(height: 8),
              TextFormField(
                controller: _descriptionController,
                decoration: const InputDecoration(labelText: 'Description'),
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
