<script lang="ts">
    import { onMount } from 'svelte';
    import {
        Library,
        RotateCw,
        Info,
        X,
        ShieldCheck,
        ShieldAlert,
        FileText,
        Folder,
        ListPlus,
        FolderTree,
        Clock,
        ArrowRight
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        browseArchiveIndexInventoryBrowseGet,
        getArchiveItemMetadataInventoryMetadataGet,
        listRecoveryQueueRestoresQueueGet,
        addFileToRecoveryQueueRestoresQueueFileFileIdPost,
        removeFromRecoveryQueueRestoresQueueItemItemIdDelete,
        addDirectoryToRecoveryQueueRestoresQueueDirectoryPost,
        searchArchiveIndexInventorySearchGet,
        type ItemMetadataSchema,
        type CartItemSchema
    } from '$lib/api';
    import { toast } from 'svelte-sonner';
    import { cn, formatLocalDate, formatLocalDateTime } from '$lib/utils';

    import { page } from '$app/state';

    let currentPath = $state('ROOT');
    let searchQuery = $state('');
    let indexedFiles = $state<FileItem[]>([]);
    let loading = $state(false);
    let searchLoading = $state(false);
    let selectedItemMetadata = $state<ItemMetadataSchema | null>(null);
    let metadataLoading = $state(false);
    let searchTimeout: any;

    // This handles the recovery queue status bar
    let restoreCartItems = $state<CartItemSchema[]>([]);
    const restoreCartPaths = $derived(new Set(restoreCartItems.map(i => i.file_path)));

    async function loadCart() {
        try {
            const response = await listRecoveryQueueRestoresQueueGet();
            if (response.data) {
                restoreCartItems = response.data;
            }
        } catch (error) {
            console.error("Failed to load cart:", error);
        }
    }

    onMount(async () => {
        await loadCart();

        // Handle deep-linked path from query params (e.g., from insights treemap)
        const targetPath = page.url.searchParams.get('path');
        if (targetPath) {
            currentPath = targetPath;
        }

        await loadIndexedFiles(currentPath);
    });

    async function loadIndexedFiles(path: string) {
        if (searchQuery.trim().length >= 3) return;
        loading = true;
        try {
            const response = await browseArchiveIndexInventoryBrowseGet({
                query: { path }
            });
            if (response.data) {
                indexedFiles = (response.data as any[]).map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    media: f.media ?? [],
                    vulnerable: f.vulnerable,
                    selected: f.selected,
                    indeterminate: f.indeterminate
                }));
            }
        } catch (error) {
            console.error("Failed to query index:", error);
            toast.error("Failed to query index");
        } finally {
            loading = false;
        }
    }

    async function searchFiles(query: string) {
        searchLoading = true;
        try {
            const response = await searchArchiveIndexInventorySearchGet({
                query: { q: query, path: currentPath }
            });
            if (response.data) {
                indexedFiles = (response.data as any[]).map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    media: f.media ?? [],
                    vulnerable: f.vulnerable,
                    selected: f.selected,
                    indeterminate: f.indeterminate
                }));
            }
        } catch (error) {
            console.error("Failed to search index:", error);
            toast.error("Search failed");
        } finally {
            searchLoading = false;
        }
    }

    $effect(() => {
        const path = currentPath;
        const query = searchQuery.trim();
        if (searchTimeout) clearTimeout(searchTimeout);

        if (query.length >= 3) {
            searchTimeout = setTimeout(() => {
                searchFiles(query);
            }, 300);
        } else {
            // If query is empty or too short, load the current directory
            searchTimeout = setTimeout(() => {
                loadIndexedFiles(path);
            }, 50);
        }
    });

    async function fetchMetadata(item: FileItem) {
        metadataLoading = true;
        try {
            const response = await getArchiveItemMetadataInventoryMetadataGet({
                query: { path: item.path }
            });
            if (response.data) {
                selectedItemMetadata = response.data;
            }
        } catch (error) {
            console.error("Failed to fetch metadata:", error);
            selectedItemMetadata = null;
        } finally {
            metadataLoading = false;
        }
    }

    async function handleToggleCart(item: FileItem) {
        const isCurrentlyInCart = item.selected;

        if (!isCurrentlyInCart) {
            // Check for vulnerability before adding
            if (item.type === 'file' && (!item.media || item.media.length === 0)) {
                toast.error(`Cannot add "${item.name}": This file has not been backed up to any media yet.`);
                return;
            }
        }

        try {
            if (isCurrentlyInCart) {
                if (item.type === 'file') {
                    const cartItem = restoreCartItems.find(i => i.file_path === item.path);
                    if (cartItem) {
                        await removeFromRecoveryQueueRestoresQueueItemItemIdDelete({
                            path: { item_id: cartItem.id }
                        });
                    }
                } else {
                    toast.warning("To remove a folder, please manage items in the Data Recovery page.");
                    return;
                }
            } else {
                if (item.type === 'file') {
                    // Fetch metadata to get the DB ID
                    const metaResponse = await getArchiveItemMetadataInventoryMetadataGet({
                        query: { path: item.path }
                    });

                    if (metaResponse.data?.id) {
                        await addFileToRecoveryQueueRestoresQueueFileFileIdPost({
                            path: { file_id: metaResponse.data.id }
                        });
                    }
                } else {
                    // It's a directory
                    await addDirectoryToRecoveryQueueRestoresQueueDirectoryPost({
                        body: { path: item.path }
                    });
                }
            }

            // Refresh everything
            await Promise.all([
                loadCart(),
                searchQuery.length >= 3 ? searchFiles(searchQuery) : loadIndexedFiles(currentPath)
            ]);

            // Refresh metadata if it's the selected item
            if (selectedItemMetadata && selectedItemMetadata.path === item.path) {
                fetchMetadata(item);
            }
        } catch (error: any) {
            toast.error(error.body?.detail || "Action failed");
        }
    }

    async function handleToggleDirectoryCart(itemPath: string) {
        try {
            await addDirectoryToRecoveryQueueRestoresQueueDirectoryPost({
                body: { path: itemPath }
            });

            // Refresh everything
            await Promise.all([
                loadCart(),
                searchQuery.length >= 3 ? searchFiles(searchQuery) : loadIndexedFiles(currentPath)
            ]);

            if (selectedItemMetadata && selectedItemMetadata.path === itemPath) {
                const dummyItem = { path: itemPath, name: '', type: 'directory' } as FileItem;
                fetchMetadata(dummyItem);
            }
        } catch (error: any) {
            toast.error(error.body?.detail || "Action failed");
        }
    }

    function formatSize(bytes: number) {
        if (bytes === 0) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }
</script>

<svelte:head>
    <title>Index Browser - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full overflow-hidden">
    <!-- INTEGRATED HEADER -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Library class="text-blue-500" size={28} />
                Archive Index
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                A view of what is stored where on archive media
            </p>
        </div>

        {#if restoreCartItems.length > 0}
            <div class="flex items-center gap-4 z-10 animate-in fade-in zoom-in duration-300">
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary bg-bg-primary px-3 py-1.5 rounded-full border border-border-color">
                    {restoreCartItems.length} items in queue
                </span>
                <Button variant="default" class="bg-success-color hover:bg-success-color/90 text-white font-black uppercase tracking-widest text-[11px] px-6 h-10 shadow-lg shadow-success-color/20" href="/restores">
                    Review Recovery Manifest
                </Button>
            </div>
        {/if}
    </header>

    <div class="flex gap-6 flex-1 min-h-0 animate-in fade-in slide-in-from-bottom-2 duration-500 overflow-hidden">
        <!-- Virtual FS Browser -->
        <div class="flex-1 flex flex-col min-h-0 relative min-w-0">
            {#if loading}
                <div class="absolute inset-0 bg-bg-primary/50 z-50 flex items-center justify-center rounded-lg">
                    <RotateCw size={32} class="animate-spin text-blue-500" />
                </div>
            {/if}
            <FileBrowser
                bind:currentPath
                bind:searchQuery
                files={indexedFiles}
                isSearching={searchLoading}
                mode="index"
                onNavigate={(path) => currentPath = path}
                onToggleTrack={handleToggleCart}
                onSelect={fetchMetadata}
            />        </div>

        <!-- Metadata Sidebar -->
        <aside class="w-96 flex flex-col gap-4 shrink-0">
            {#if selectedItemMetadata}
                <Card class="flex-1 overflow-hidden flex flex-col bg-bg-secondary border-border-color shadow-2xl relative">
                    <div class="p-6 border-b border-border-color bg-bg-tertiary/30">
                        <div class="flex justify-between items-start mb-4">
                            <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20">
                                {#if selectedItemMetadata.type === 'directory'}
                                    <Folder size={24} />
                                {:else}
                                    <FileText size={24} />
                                {/if}
                            </div>
                            <button class="text-text-secondary hover:text-text-primary transition-colors" onclick={() => selectedItemMetadata = null}>
                                <X size={20} />
                            </button>
                        </div>
                        <h3 class="text-lg font-black text-text-primary leading-tight truncate" title={selectedItemMetadata.path}>
                            {selectedItemMetadata.path.split('/').pop()}
                        </h3>
                        <p class="text-[10px] mono text-text-secondary mt-1 opacity-60 truncate italic">{selectedItemMetadata.path}</p>
                    </div>

                    <ScrollArea class="flex-1">
                        <div class="p-6 space-y-8">
                            <!-- Core Stats -->
                            <div class="grid grid-cols-2 gap-4">
                                <div class="space-y-1">
                                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">
                                        {selectedItemMetadata.type === 'directory' ? 'Total Aggregate Size' : 'File Size'}
                                    </span>
                                    <span class="text-sm font-bold text-text-primary mono">{formatSize(selectedItemMetadata.size)}</span>
                                </div>
                                <div class="space-y-1">
                                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">Last Indexed</span>
                                    <span class="text-sm font-bold text-text-primary mono">{formatLocalDate(selectedItemMetadata.last_seen_timestamp)}</span>
                                </div>
                                {#if selectedItemMetadata.type === 'directory'}
                                    <div class="space-y-1 col-span-2 mt-2">
                                        <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">Recursive Child Count</span>
                                        <span class="text-sm font-bold text-text-primary mono">{selectedItemMetadata.child_count?.toLocaleString()} Indexed Files</span>
                                    </div>
                                {/if}
                            </div>

                            {#if selectedItemMetadata.type === 'file'}
                                <!-- Hash -->
                                <div class="space-y-2">
                                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block">SHA-256 Fingerprint</span>
                                    <div class="bg-bg-primary p-3 rounded-lg border border-border-color/50 break-all mono text-[10px] text-blue-400/80 leading-relaxed">
                                        {selectedItemMetadata.sha256_hash || 'Pending computation...'}
                                    </div>
                                </div>

                                <!-- Backup Locations -->
                                <div class="space-y-4">
                                    <div class="flex items-center gap-2">
                                        <ShieldCheck size={14} class="text-success-color" />
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">Storage Locations</span>
                                    </div>

                                    <div class="space-y-2">
                                        {#each selectedItemMetadata.versions || [] as version}
                                            <div class="bg-bg-primary/50 border border-border-color rounded-lg p-3 group hover:border-blue-500/30 transition-all">
                                                <div class="flex justify-between items-center mb-2">
                                                    <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-blue-500/10 text-blue-400 text-[10px] font-black border border-blue-500/20">
                                                        {(version as any).media_id || (version as any).media_identifier}
                                                    </span>
                                                    <span class="text-[9px] font-bold text-text-secondary opacity-40 uppercase tracking-tighter">
                                                        {(version as any).media_type}
                                                    </span>
                                                </div>
                                                <div class="flex flex-col gap-1">
                                                    <div class="flex items-center gap-2 text-[10px] text-text-secondary">
                                                        <FolderTree size={12} class="opacity-50" />
                                                        <span class="mono">POS: {(version as any).archive_id || (version as any).file_number}</span>
                                                    </div>
                                                    <div class="flex items-center gap-1.5 opacity-60">
                                                        <Clock size={12} class="opacity-50" />
                                                        <span>Archived: {formatLocalDateTime((version as any).timestamp || (version as any).created_at)}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        {:else}
                                            <div class="py-8 text-center border-2 border-dashed border-border-color rounded-xl opacity-30">
                                                <p class="text-[10px] font-black uppercase tracking-widest">No versions stored on media.</p>
                                            </div>
                                        {/each}
                                    </div>
                                </div>
                            {/if}
                        </div>
                    </ScrollArea>

                    {#if selectedItemMetadata.type === 'file' && (selectedItemMetadata.versions?.length ?? 0) > 0}
                        <div class="p-6 bg-bg-tertiary/30 border-t border-border-color mt-auto">
                            <Button class="w-full h-11 font-black uppercase tracking-widest text-[11px] shadow-lg shadow-blue-500/10" onclick={() => handleToggleCart({path: selectedItemMetadata?.path || '', type: 'file', name: '', media: (selectedItemMetadata?.versions || []).map((v: any) => v.media_id || v.media_identifier), selected: selectedItemMetadata?.selected} as FileItem)}>
                                <ShieldCheck size={16} class="mr-2" />
                                {selectedItemMetadata.selected ? 'Remove from Queue' : 'Add to Recovery Queue'}
                            </Button>
                        </div>
                    {:else if selectedItemMetadata.type === 'directory' && (selectedItemMetadata.child_count || 0) > 0}
                        <div class="p-6 bg-bg-tertiary/30 border-t border-border-color mt-auto">
                            <Button variant="outline" class={cn("w-full h-11 font-black uppercase tracking-widest text-[11px]", "border-success-color/30 text-success-color hover:bg-success-color/10")} onclick={() => handleToggleDirectoryCart(selectedItemMetadata?.path || '')} disabled={selectedItemMetadata.selected}>
                                <ListPlus size={16} class="mr-2" />
                                {#if selectedItemMetadata.selected}
                                    Folder Fully Queued
                                {:else}
                                    Add Folder to Recovery Queue
                                {/if}
                            </Button>
                        </div>
                    {/if}
                </Card>
            {:else}
                <div class="flex-1 border-2 border-dashed border-border-color rounded-xl flex flex-col items-center justify-center p-12 text-center opacity-20">
                    <Library size={48} class="mb-4 text-blue-500" />
                    <p class="text-xs font-black uppercase tracking-widest leading-relaxed">
                        Select an item from the index<br>to view detailed metadata and<br>storage locations.
                    </p>
                </div>
            {/if}
        </aside>
    </div>
</div>
