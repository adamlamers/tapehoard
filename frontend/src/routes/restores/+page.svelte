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
    import { Card } from '$lib/components/ui/card';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        listCartRestoresCartGet,
        getManifestRestoresManifestGet,
        removeFromCartRestoresCartItemIdDelete,
        clearCartRestoresCartClearPost,
        getSettingsSystemSettingsGet,
        triggerRestoreRestoresTriggerPost,
        browseCartRestoresCartBrowseGet,
        type CartItemSchema,
        type RestoreManifestSchema,
        type CartFileItemSchema
    } from '$lib/api';
    import { cn } from '$lib/utils';
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
            const settingsRes = await getSettingsSystemSettingsGet();
            if (settingsRes.data?.restore_destinations) {
                restoreDests = JSON.parse(settingsRes.data.restore_destinations);
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
            const manifestRes = await getManifestRestoresManifestGet();
            if (manifestRes.data) manifest = manifestRes.data;
        } catch (err) {
            console.error("Failed to load manifest:", err);
        }
    }

    async function loadCartFiles(path: string) {
        loading = true;
        try {
            const response = await browseCartRestoresCartBrowseGet({
                query: { path }
            });
            if (response.data) {
                cartFiles = (response.data as CartFileItemSchema[]).map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as any,
                    size: f.size ?? null,
                    media: f.media ?? []
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
            await triggerRestoreRestoresTriggerPost({
                body: { destination: selectedDest }
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
            await clearCartRestoresCartClearPost();
            cartFiles = [];
            manifest = null;
            await loadData();
            toast.info("Recovery queue cleared");
        } catch (error: any) {
            console.error("Failed to clear queue:", error);
            toast.error("Failed to clear recovery queue");
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

    onMount(loadData);
</script>

<svelte:head>
    <title>Data Recovery - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full overflow-hidden animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden shrink-0">
        <div class="absolute inset-0 bg-gradient-to-r from-success-color/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <History class="text-success-color" size={28} />
                Data Recovery
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Recovery Queue & Physical Media Manifest
            </p>
        </div>

        <div class="flex gap-3 z-10">
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-border-color hover:bg-error-color/5 hover:text-error-color hover:border-error-color/30" onclick={clearCart} disabled={(manifest?.total_files || 0) === 0}>
                <Trash2 size={14} class="mr-2" /> Clear Queue
            </Button>
            <Button variant="default" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] bg-success-color hover:bg-success-color/90" disabled={(manifest?.total_files || 0) === 0 || !selectedDest || restoring} onclick={initiateRestore}>
                {#if restoring}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <ShieldCheck size={14} class="mr-2" /> Initiate Recovery
                {/if}
            </Button>
        </div>
    </header>

    {#if (manifest?.total_files || 0) === 0 && !loading}
        <div class="flex-1 flex flex-col items-center justify-center p-12 text-center animate-in fade-in zoom-in duration-500">
            <div class="max-w-2xl flex flex-col items-center">
                <div class="w-24 h-24 bg-bg-tertiary rounded-full flex items-center justify-center mb-8 border-2 border-dashed border-border-color opacity-50">
                    <History size={48} class="text-text-secondary" strokeWidth={1} />
                </div>
                <h2 class="text-2xl font-black uppercase tracking-tighter text-text-primary">Recovery Queue is Empty</h2>
                <p class="text-[11px] font-bold uppercase tracking-[0.2em] mt-4 text-text-secondary leading-loose opacity-60">
                    You haven't selected any files for restoration yet. Use the Index Browser to find and queue the items you need to recover from your archives.
                </p>
                <Button variant="default" class="mt-10 h-12 px-10 font-black uppercase tracking-widest text-[11px] shadow-lg shadow-blue-500/20" href="/index-browser">
                    Browse Virtual Index <ArrowRight size={14} class="ml-2" />
                </Button>
            </div>
        </div>
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
                    <h3 class="text-[10px] font-black uppercase tracking-widest text-text-secondary mb-4 opacity-50">Queue Statistics</h3>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="p-4 bg-bg-primary/40 border border-border-color/40 rounded-xl">
                            <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary block mb-1">Total Files</span>
                            <span class="text-xl font-black text-text-primary mono">{manifest?.total_files || 0}</span>
                        </div>
                        <div class="p-4 bg-bg-primary/40 border border-border-color/40 rounded-xl">
                            <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary block mb-1">Recovery Size</span>
                            <span class="text-xl font-black text-text-primary mono">{formatSize(manifest?.total_size || 0)}</span>
                        </div>
                    </div>
                </Card>

                <!-- DESTINATION SELECTOR -->
                <Card class="bg-bg-secondary border-border-color shadow-xl overflow-hidden">
                    <div class="p-5 border-b border-border-color bg-bg-tertiary/30 flex items-center gap-3">
                        <MapPin size={16} class="text-success-color" />
                        <h2 class="text-xs font-black uppercase tracking-widest text-text-primary">Recovery Target</h2>
                    </div>
                    <div class="p-5 space-y-4">
                        <div class="space-y-2">
                            <label for="destination" class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-50 ml-1">Restore to Host Path</label>
                            <select
                                id="destination"
                                bind:value={selectedDest}
                                class="w-full h-12 bg-bg-primary border border-border-color rounded-xl px-4 text-sm font-bold text-text-primary outline-none focus:ring-2 focus:ring-success-color/20 transition-all appearance-none cursor-pointer"
                            >
                                {#each restoreDests as dest}
                                    <option value={dest}>{dest}</option>
                                {/each}
                                {#if restoreDests.length === 0}
                                    <option value="">No destinations configured</option>
                                {/if}
                            </select>
                        </div>
                        <p class="text-[10px] text-text-secondary leading-relaxed italic opacity-60">
                            Files will be restored into this directory, maintaining their original folder structure.
                        </p>
                    </div>
                </Card>

                <!-- MEDIA MANIFEST -->
                <Card class="bg-bg-secondary border-border-color shadow-xl flex flex-col min-h-0">
                    <div class="p-5 border-b border-border-color bg-bg-tertiary/30 flex items-center gap-3">
                        <Database size={16} class="text-blue-400" />
                        <h2 class="text-xs font-black uppercase tracking-widest text-text-primary">Physical Manifest</h2>
                    </div>

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
                                        <span class="text-sm font-black text-text-primary mono">{media.identifier}</span>
                                        <span class="text-[9px] font-black uppercase text-blue-400">{media.media_type}</span>
                                    </div>
                                    <div class="flex gap-3 mt-1">
                                        <span class="text-[10px] font-bold text-text-secondary opacity-60 uppercase">{media.file_count} Files</span>
                                        <span class="text-[10px] font-bold text-text-secondary opacity-60 uppercase border-l border-border-color pl-3">{formatSize(media.total_size)}</span>
                                    </div>
                                </div>
                            </div>
                        {:else}
                            <div class="py-12 text-center opacity-20 border-2 border-dashed border-border-color rounded-xl">
                                <p class="text-[10px] font-black uppercase tracking-widest">No Media Required</p>
                            </div>
                        {/each}
                    </div>

                    <div class="p-5 bg-bg-tertiary/20 border-t border-border-color">
                        <div class="flex items-start gap-3">
                            <ShieldCheck size={14} class="text-success-color shrink-0 mt-0.5" />
                            <p class="text-[10px] text-text-secondary leading-normal">
                                Verification active: Media identifiers will be checked physically before extraction. Recovery will proceed sequentially by media to minimize hardware cycles.
                            </p>
                        </div>
                    </div>
                </Card>
            </aside>
        </div>
    {/if}
</div>
