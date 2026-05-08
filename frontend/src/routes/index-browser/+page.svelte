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
        ArrowRight,
        AlertTriangle
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import { Card } from '$lib/components/ui/card';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        archiveBrowse,
        archiveMetadata,
        getRestoreQueue,
        addFileToRestoreQueue,
        removeFromRestoreQueue,
        addDirectoryToRestoreQueue,
        archiveSearch,
        type ItemMetadataSchema,
        type CartItemSchema
    } from '$lib/api';
    import { toast } from 'svelte-sonner';
    import { cn, formatLocalDate, formatLocalDateTime, formatSize } from '$lib/utils';

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
            const response = await getRestoreQueue();
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
            const response = await archiveBrowse({
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
                    indeterminate: f.indeterminate,
                    is_partially_archived: f.is_partially_archived ?? false,
                    archived_bytes: f.archived_bytes ?? undefined
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
            const response = await archiveSearch({
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
                    indeterminate: f.indeterminate,
                    is_partially_archived: f.is_partially_archived ?? false,
                    archived_bytes: f.archived_bytes ?? undefined
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
            const response = await archiveMetadata({
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
                        await removeFromRestoreQueue({
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
                    const metaResponse = await archiveMetadata({
                        query: { path: item.path }
                    });

                    if (metaResponse.data?.id) {
                        await addFileToRestoreQueue({
                            path: { file_id: metaResponse.data.id }
                        });
                    }
                } else {
                    // It's a directory
                    await addDirectoryToRestoreQueue({
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
            await addDirectoryToRestoreQueue({
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

</script>

<svelte:head>
    <title>Index Browser - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full overflow-hidden">
    <PageHeader
        title="Archive index"
        description="A view of what is stored where on archive media"
        icon={Library}
    >
        {#snippet actions()}
            {#if restoreCartItems.length > 0}
                <div class="flex items-center gap-3 z-10 animate-in fade-in zoom-in duration-300">
                    <span class="text-5xs font-bold text-text-secondary bg-bg-primary px-3 py-1.5 rounded-full border border-border-color">
                        {restoreCartItems.length} items in queue
                    </span>
                    <Button variant="default" class="bg-success-color hover:bg-success-color/90 text-white" href="/restores">
                        Review recovery manifest
                    </Button>
                </div>
            {/if}
        {/snippet}
    </PageHeader>

    <div class="flex gap-6 flex-1 min-h-0 animate-in fade-in slide-in-from-bottom-2 duration-500 overflow-hidden">
        <!-- Virtual FS Browser -->
        <div class="flex-1 flex flex-col min-h-0 relative min-w-0">
            {#if loading}
                <div class="absolute inset-0 bg-bg-primary/50 z-50 flex items-center justify-center rounded-lg">
                    <RotateCw size={24} class="animate-spin text-blue-500" />
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
                onOpenLocation={(item) => {
                    // Navigate to parent directory of the file
                    const parts = item.path.split('/').filter(Boolean);
                    parts.pop(); // Remove the file/directory name
                    const parentPath = parts.length === 0 ? 'ROOT' : '/' + parts.join('/');
                    currentPath = parentPath;
                }}
            />        </div>

        <!-- Metadata Sidebar -->
        <aside class="w-80 flex flex-col gap-4 shrink-0">
            {#if selectedItemMetadata}
                <Card class="flex-1 overflow-hidden flex flex-col bg-bg-secondary border-border-color shadow-2xl relative">
                    <div class="p-5 border-b border-border-color bg-bg-tertiary/30">
                        <div class="flex justify-between items-start mb-3">
                            <div class="p-2 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20">
                                {#if selectedItemMetadata.type === 'directory'}
                                    <Folder size={18} />
                                {:else}
                                    <FileText size={18} />
                                {/if}
                            </div>
                            <button class="text-text-secondary hover:text-text-primary transition-colors" onclick={() => selectedItemMetadata = null}>
                                <X size={18} />
                            </button>
                        </div>
                        <h3 class="text-sm font-bold text-text-primary leading-tight truncate" title={selectedItemMetadata.path}>
                            {selectedItemMetadata.path.split('/').pop()}
                        </h3>
                        <p class="text-5xs mono text-text-secondary mt-1 opacity-50 truncate italic">{selectedItemMetadata.path}</p>
                    </div>

                    <ScrollArea class="flex-1">
                        <div class="p-5 space-y-6">
                            <!-- Core Stats -->
                            <div class="grid grid-cols-2 gap-4">
                                <div class="space-y-1">
                                    <span class="text-xs font-medium text-text-secondary opacity-60 block">
                                        {selectedItemMetadata.type === 'directory' ? 'Aggregate Size' : 'Archived Size'}
                                    </span>
                                    <span class="text-xs font-semibold text-text-primary mono">{formatSize(selectedItemMetadata.type === 'file' ? (selectedItemMetadata.archived_bytes || 0) : selectedItemMetadata.size)}</span>
                                </div>
                                <div class="space-y-1">
                                    <span class="text-xs font-medium text-text-secondary opacity-60 block">Last Indexed</span>
                                    <span class="text-xs font-semibold text-text-primary mono">{formatLocalDate(selectedItemMetadata.last_seen_timestamp)}</span>
                                </div>
                                {#if selectedItemMetadata.type === 'directory'}
                                    <div class="space-y-1 col-span-2">
                                        <span class="text-xs font-medium text-text-secondary opacity-60 block">Child Count</span>
                                        <span class="text-xs font-semibold text-text-primary mono">{selectedItemMetadata.child_count?.toLocaleString()} Indexed Files</span>
                                    </div>
                                {/if}
                            </div>

                            {#if selectedItemMetadata.type === 'file'}
                                {#if selectedItemMetadata.is_partially_archived}
                                    <div class="p-3 bg-orange-500/5 border border-orange-500/20 rounded-lg space-y-1">
                                        <div class="flex items-center gap-2">
                                            <AlertTriangle size={14} class="text-orange-400" />
                                            <span class="text-xs font-semibold text-orange-400">Partially Archived</span>
                                        </div>
                                        <p class="text-5xs text-text-secondary opacity-60 leading-relaxed">
                                            Only {formatSize(selectedItemMetadata.archived_bytes || 0)} of {formatSize(selectedItemMetadata.size)} has been written to archive media. The remaining {formatSize(selectedItemMetadata.size - (selectedItemMetadata.archived_bytes || 0))} was not archived because the target media became full.
                                        </p>
                                    </div>
                                {/if}

                                <!-- Hash -->
                                <div class="space-y-2">
                                    <span class="text-xs font-medium text-text-secondary opacity-60 block">SHA-256 Fingerprint</span>
                                    <div class="bg-bg-primary p-2.5 rounded-lg border border-border-color/50 break-all mono text-5xs text-blue-400/80 leading-relaxed">
                                        {selectedItemMetadata.sha256_hash || 'Pending computation...'}
                                    </div>
                                </div>

                                <!-- Backup Locations -->
                                <div class="space-y-3">
                                    <div class="flex items-center gap-2">
                                        <ShieldCheck size={12} class="text-success-color" />
                                        <span class="text-xs font-medium text-text-secondary opacity-60">Storage Locations</span>
                                    </div>

                                    <div class="space-y-2">
                                        {#each selectedItemMetadata.versions || [] as version}
                                            <div class="bg-bg-primary/50 border border-border-color rounded-lg p-2 group hover:border-blue-500/30 transition-all">
                                                <div class="flex items-center gap-2 mb-1">
                                                    <span class="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 text-xs font-semibold border border-blue-500/20 truncate">
                                                        {(version as any).media_id}
                                                    </span>
                                                    <span class="text-xs font-medium text-text-secondary opacity-40 uppercase tracking-tight ml-auto shrink-0">
                                                        {(version as any).media_type}
                                                    </span>
                                                </div>
                                                <div class="flex flex-col gap-0.5 text-xs">
                                                    <div class="flex items-center gap-1.5 text-text-secondary">
                                                        <FolderTree size={10} class="opacity-50 shrink-0" />
                                                        <span class="mono truncate">{(version as any).archive_id}</span>
                                                        <span class="text-text-secondary opacity-40 text-[10px] ml-auto shrink-0">
                                                            {(version as any).media_type === 'tape' ? 'POS' : 'Path'}
                                                        </span>
                                                    </div>
                                                    <div class="flex items-center gap-1.5 opacity-60">
                                                        <Clock size={10} class="opacity-50 shrink-0" />
                                                        <span class="truncate">Archived: {formatLocalDateTime((version as any).timestamp || (version as any).created_at)}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        {:else}
                                            <div class="py-6 text-center border-2 border-dashed border-border-color rounded-xl opacity-30">
                                                <p class="text-[10px] font-medium text-text-secondary uppercase tracking-tight">No versions stored on media.</p>
                                            </div>
                                        {/each}
                                    </div>
                                </div>
                            {/if}
                        </div>
                    </ScrollArea>

                    {#if selectedItemMetadata.type === 'file' && (selectedItemMetadata.versions?.length ?? 0) > 0}
                        <div class="p-5 bg-bg-tertiary/30 border-t border-border-color mt-auto">
                            <Button class="w-full h-9 font-semibold text-xs shadow-lg shadow-blue-500/10" onclick={() => handleToggleCart({path: selectedItemMetadata?.path || '', type: 'file', name: '', media: (selectedItemMetadata?.versions || []).map((v: any) => v.media_id || v.media_identifier), selected: selectedItemMetadata?.selected} as FileItem)}>
                                <ShieldCheck size={14} class="mr-2" />
                                {selectedItemMetadata.selected ? 'Remove from recovery queue' : 'Add to recovery queue'}
                            </Button>
                        </div>
                    {:else if selectedItemMetadata.type === 'directory' && (selectedItemMetadata.child_count || 0) > 0}
                        <div class="p-5 bg-bg-tertiary/30 border-t border-border-color mt-auto">
                            <Button variant="outline" class={cn("w-full h-9 font-semibold text-xs", "border-success-color/30 text-success-color hover:bg-success-color/10")} onclick={() => handleToggleDirectoryCart(selectedItemMetadata?.path || '')} disabled={selectedItemMetadata.selected}>
                                <ListPlus size={14} class="mr-2" />
                                {#if selectedItemMetadata.selected}
                                    Folder fully queued
                                {:else}
                                    Add folder to recovery queue
                                {/if}
                            </Button>
                        </div>
                    {/if}
                </Card>
            {:else}
                <div class="flex-1 border-2 border-dashed border-border-color rounded-xl flex flex-col items-center justify-center p-8 text-center opacity-20">
                    <Library size={40} class="mb-3 text-blue-500" />
                    <p class="text-xs font-medium text-text-secondary leading-relaxed">
                        Select an item from the index<br>to view detailed metadata and<br>storage locations.
                    </p>
                </div>
            {/if}
        </aside>
    </div>
</div>
