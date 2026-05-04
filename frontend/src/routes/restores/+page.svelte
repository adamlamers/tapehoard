<script lang="ts">
    import { onMount } from 'svelte';
    import {
        History,
        Trash2,
        RotateCw,
        Database,
        CassetteTape,
        HardDrive,
        ArrowRight,
        X,
        FileText,
        ShieldCheck,
        ShieldAlert,
        MapPin,
        Library
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import EmptyState from '$lib/components/ui/EmptyState.svelte';
    import { Card } from '$lib/components/ui/card';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        getRestoreQueue,
        getRestoreManifest,
        removeFromRestoreQueue,
        clearRestoreQueue,
        getSettings,
        triggerRestore,
        browseRestoreQueue,
        type CartItemSchema,
        type RestoreManifestSchema,
        type CartFileItemSchema
    } from '$lib/api';
    import { cn, formatSize } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let currentPath = $state('ROOT');
    let cartFiles = $state<FileItem[]>([]);
    let manifest = $state<RestoreManifestSchema | null>(null);
    let restoreDests = $state<string[]>([]);
    let selectedDest = $state("");
    let loading = $state(true);
    let restoring = $state(false);

    async function loadData() {
        loading = true;
        try {
            const settingsRes = await getSettings();
            const settingsData = settingsRes.data as Record<string, string>;
            if (settingsData?.restore_destinations) {
                restoreDests = JSON.parse(settingsData.restore_destinations);
                if (restoreDests.length > 0 && !selectedDest) selectedDest = restoreDests[0];
            }

            await Promise.all([
                loadCartFiles(currentPath),
                refreshManifest()
            ]);

        } catch (error) {
            console.error("Failed to load recovery details:", error);
            toast.error("Failed to load recovery queue");
        } finally {
            loading = false;
        }
    }

    async function refreshManifest() {
        try {
            const manifestRes = await getRestoreManifest();
            if (manifestRes.data) manifest = manifestRes.data;
        } catch (err) {
            console.error("Failed to load manifest:", err);
        }
    }

    async function loadCartFiles(path: string) {
        loading = true;
        try {
            const response = await browseRestoreQueue({
                query: { path }
            });
            if (response.data) {
                cartFiles = (response.data as CartFileItemSchema[]).map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as any,
                    size: f.size ?? null
                }));
            }
        } catch (error) {
            console.error("Failed to browse cart:", error);
            toast.error("Failed to load recovery folder structure");
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        if (currentPath) {
            loadCartFiles(currentPath);
        }
    });

    async function initiateRestore() {
        if (!selectedDest) {
            toast.error("Please select a recovery destination");
            return;
        }

        restoring = true;
        try {
            await triggerRestore({
                body: { destination_path: selectedDest }
            });
            toast.success("Recovery job initiated! Check System Activity for progress.");
            // Reset queue UI
            cartFiles = [];
            manifest = null;
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to initiate recovery");
        } finally {
            restoring = false;
        }
    }

    async function handleRemove(item: FileItem) {
        // Find the DB ID for this specific file in the cart
        // This is a bit tricky with browseCart as it doesn't return cart_item.id
        // We'll just clear the whole folder or rely on the Data Recovery page being a tree view
        // For now, removing individual items from the tree isn't fully implemented
        // so we'll just show a toast instruction.
        toast.info("Individual item removal from tree view coming soon. Use 'Clear Queue' for now.");
    }

    async function clearCart() {
        if (!confirm("Are you sure you want to clear the entire recovery queue?")) return;
        try {
            await clearRestoreQueue();
            cartFiles = [];
            manifest = null;
            await loadData();
            toast.info("Recovery queue cleared");
        } catch (error: any) {
            console.error("Failed to clear queue:", error);
            toast.error("Failed to clear recovery queue");
        }
    }

    onMount(loadData);
</script>

<svelte:head>
    <title>Data Recovery - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full overflow-hidden animate-in fade-in duration-700">
    <PageHeader
        title="Data recovery"
        description="Recovery queue & physical media manifest"
        icon={History}
    >
        {#snippet actions()}
            <Button variant="outline" onclick={clearCart} disabled={(manifest?.total_files || 0) === 0}>
                <Trash2 size={14} class="mr-2" /> Clear queue
            </Button>
            <Button variant="default" class="bg-success-color hover:bg-success-color/90 border-none" disabled={(manifest?.total_files || 0) === 0 || !selectedDest || restoring} onclick={initiateRestore}>
                {#if restoring}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <ShieldCheck size={14} class="mr-2" /> Initiate recovery
                {/if}
            </Button>
        {/snippet}
    </PageHeader>

    {#if (manifest?.total_files || 0) === 0 && !loading}
        <EmptyState
            icon={History}
            title="Recovery queue is empty"
            description="You haven't selected any files for restoration yet. Use the Index Browser to find and queue the items you need to recover from your archives."
        >
            {#snippet action()}
                <Button variant="default" class="px-8 shadow-lg shadow-blue-500/20" href="/index-browser">
                    Browse virtual index <ArrowRight size={14} class="ml-2" />
                </Button>
            {/snippet}
        </EmptyState>
    {:else}
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 flex-1 min-h-0">
            <!-- RECOVERY STRUCTURE TREE -->
            <div class="lg:col-span-2 flex flex-col min-h-0 relative min-w-0">
                {#if loading && cartFiles.length === 0}
                    <div class="absolute inset-0 bg-bg-primary/50 z-50 flex items-center justify-center rounded-lg">
                        <RotateCw size={32} class="animate-spin text-blue-500" />
                    </div>
                {/if}
                <FileBrowser
                    bind:currentPath
                    files={cartFiles}
                    mode="cart"
                    onNavigate={(path) => currentPath = path}
                    onToggleTrack={handleRemove}
                />
            </div>

            <!-- SIDEBAR: MANIFEST & SETTINGS -->
            <aside class="flex flex-col gap-6 min-h-0 overflow-y-auto pr-2 pb-4">
                <!-- Queue Summary -->
                <Card class="p-6 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-xl">
                    <span class="text-xs font-medium text-text-secondary mb-4 opacity-50 block">Queue statistics</span>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="p-4 bg-bg-primary/40 border border-border-color/40 rounded-xl">
                            <span class="text-[10px] font-medium text-text-secondary block mb-1">Total files</span>
                            <span class="text-xl font-bold text-text-primary mono">{manifest?.total_files || 0}</span>
                        </div>
                        <div class="p-4 bg-bg-primary/40 border border-border-color/40 rounded-xl">
                            <span class="text-[10px] font-medium text-text-secondary block mb-1">Recovery size</span>
                            <span class="text-xl font-bold text-text-primary mono">{formatSize(manifest?.total_size || 0)}</span>
                        </div>
                    </div>
                </Card>

                <!-- DESTINATION SELECTOR -->
                <Card class="bg-bg-secondary border-border-color shadow-xl overflow-hidden">
                    <SectionHeader title="Recovery target" icon={MapPin} iconColor="text-success-color" class="p-4 bg-bg-tertiary/30 border-b border-border-color" />
                    <div class="p-5 space-y-4">
                        <div class="space-y-2">
                            <label for="destination" class="text-xs font-medium text-text-secondary opacity-50 ml-1">Restore to host path</label>
                            <select
                                id="destination"
                                bind:value={selectedDest}
                                class="w-full h-10 bg-bg-primary border border-border-color rounded-xl px-4 text-sm font-medium text-text-primary outline-none focus:ring-2 focus:ring-success-color/20 transition-all appearance-none cursor-pointer"
                            >
                                {#each restoreDests as dest}
                                    <option value={dest}>{dest}</option>
                                {/each}
                                {#if restoreDests.length === 0}
                                    <option value="">No destinations configured</option>
                                {/if}
                            </select>
                        </div>
                        <p class="text-xs text-text-secondary leading-relaxed italic opacity-60">
                            Files will be restored into this directory, maintaining their original folder structure.
                        </p>
                    </div>
                </Card>

                <!-- MEDIA MANIFEST -->
                <Card class="bg-bg-secondary border-border-color shadow-xl flex flex-col min-h-0">
                    <SectionHeader title="Physical manifest" icon={Database} iconColor="text-blue-400" class="p-4 bg-bg-tertiary/30 border-b border-border-color" />

                    <div class="p-5 space-y-3 flex-1 overflow-y-auto">
                        {#each manifest?.media_required || [] as media}
                            <div class="bg-bg-primary/50 border border-border-color rounded-xl p-4 flex items-center gap-4 group hover:border-blue-500/30 transition-all">
                                <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500">
                                    {#if media.media_type === 'tape'}<CassetteTape size={20} />{/if}
                                    {#if media.media_type === 'hdd'}<HardDrive size={20} />{/if}
                                    {#if media.media_type === 'cloud'}<Library size={20} />{/if}
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between items-center">
                                        <span class="text-sm font-bold text-text-primary mono">{media.identifier}</span>
                                        <span class="text-[10px] font-medium text-blue-400">{media.media_type}</span>
                                    </div>
                                    <div class="flex gap-3 mt-1">
                                        <span class="text-[10px] font-medium text-text-secondary opacity-60">{media.file_count} files</span>
                                        <span class="text-[10px] font-medium text-text-secondary opacity-60 border-l border-border-color pl-3">{formatSize(media.total_size)}</span>
                                    </div>
                                </div>
                            </div>
                        {:else}
                            <div class="py-12 text-center opacity-20 border-2 border-dashed border-border-color rounded-xl">
                                <p class="text-xs font-medium">No media required</p>
                            </div>
                        {/each}
                    </div>

                    <div class="p-5 bg-bg-tertiary/20 border-t border-border-color">
                        <div class="flex items-start gap-3">
                            <ShieldCheck size={14} class="text-success-color shrink-0 mt-0.5" />
                            <p class="text-3xs text-text-secondary leading-normal">
                                Verification active: Media identifiers will be checked physically before extraction. Recovery will proceed sequentially by media to minimize hardware cycles.
                            </p>
                        </div>
                    </div>
                </Card>
            </aside>
        </div>
    {/if}
</div>
