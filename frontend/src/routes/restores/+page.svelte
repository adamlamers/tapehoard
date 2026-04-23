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
        Info,
        ShieldCheck,
        MapPin
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import {
        listCartRestoresCartGet,
        getManifestRestoresManifestGet,
        removeFromCartRestoresCartItemIdDelete,
        clearCartRestoresCartClearPost,
        getSettingsSystemSettingsGet,
        type CartItemSchema,
        type RestoreManifestSchema
    } from '$lib/api';
    import { cn } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let cartItems = $state<CartItemSchema[]>([]);
    let manifest = $state<RestoreManifestSchema | null>(null);
    let restoreDests = $state<string[]>([]);
    let selectedDest = $state("");
    let loading = $state(true);

    async function loadData() {
        loading = true;
        try {
            const [cartRes, manifestRes, settingsRes] = await Promise.all([
                listCartRestoresCartGet(),
                getManifestRestoresManifestGet(),
                getSettingsSystemSettingsGet()
            ]);

            if (cartRes.data) cartItems = cartRes.data;
            if (manifestRes.data) manifest = manifestRes.data;

            if (settingsRes.data?.restore_destinations) {
                restoreDests = JSON.parse(settingsRes.data.restore_destinations);
                if (restoreDests.length > 0) selectedDest = restoreDests[0];
            }
        } catch (error) {
            toast.error("Failed to load restore details");
        } finally {
            loading = false;
        }
    }

    async function removeItem(itemId: number) {
        try {
            await removeFromCartRestoresCartItemIdDelete({ path: { item_id: itemId } });
            await loadData();
        } catch (error) {
            toast.error("Failed to remove item");
        }
    }

    async function clearCart() {
        if (!confirm("Clear entire restore cart?")) return;
        try {
            await clearCartRestoresCartClearPost();
            await loadData();
            toast.info("Cart cleared");
        } catch (error) {
            toast.error("Failed to clear cart");
        }
    }

    onMount(loadData);

    function formatSize(bytes: number) {
        if (bytes === 0) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
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
    <title>Restore Management - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full">
    <!-- HEADER -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-success-color/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <History class="text-success-color" size={28} />
                Restore Management
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Cart Review & Physical Media Manifest
            </p>
        </div>

        <div class="flex gap-3 z-10">
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-border-color hover:bg-error-color/5 hover:text-error-color hover:border-error-color/30" onclick={clearCart} disabled={cartItems.length === 0}>
                <Trash2 size={14} class="mr-2" /> Clear Cart
            </Button>
            <Button variant="default" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] bg-success-color hover:bg-success-color/90" disabled={cartItems.length === 0 || !selectedDest}>
                <ShieldCheck size={14} class="mr-2" /> Initiate Restore
            </Button>
        </div>
    </header>

    {#if loading && cartItems.length === 0}
        <div class="flex flex-col items-center justify-center py-24 gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-success-color" />
            <span class="text-xs font-black uppercase tracking-widest">Generating Manifest...</span>
        </div>
    {:else if cartItems.length === 0}
        <Card class="flex-1 border-2 border-dashed border-border-color flex flex-col items-center justify-center p-12 text-center opacity-30">
            <History size={64} class="mb-4" strokeWidth={1} />
            <p class="text-lg font-black uppercase tracking-widest">Restore Cart is Empty</p>
            <p class="text-[11px] font-bold uppercase tracking-[0.2em] mt-2">Go to the Index Browser to select files for recovery.</p>
            <Button variant="outline" class="mt-8 border-border-color" href="/index-browser">
                Browse Index <ArrowRight size={14} class="ml-2" />
            </Button>
        </Card>
    {:else}
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 flex-1 min-h-0">
            <!-- CART LIST -->
            <div class="lg:col-span-2 flex flex-col min-h-0">
                <Card class="flex-1 overflow-hidden flex flex-col bg-bg-secondary border-border-color shadow-xl">
                    <div class="p-6 border-b border-border-color flex justify-between items-center bg-bg-tertiary/30">
                        <h3 class="text-[11px] font-black uppercase tracking-widest text-text-primary">Queued for Restore ({cartItems.length})</h3>
                        <span class="text-xs font-bold mono text-text-secondary">{formatSize(manifest?.total_size || 0)}</span>
                    </div>
                    <ScrollArea class="flex-1">
                        <div class="divide-y divide-border-color/30">
                            {#each cartItems as item (item.id)}
                                <div class="p-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors group">
                                    <div class="flex items-center gap-4 min-w-0">
                                        <div class="p-2 bg-bg-primary rounded-lg border border-border-color/50 text-text-secondary">
                                            <FileText size={18} />
                                        </div>
                                        <div class="flex flex-col min-w-0">
                                            <span class="text-[13px] font-bold text-text-primary truncate">{item.file_path.split('/').pop()}</span>
                                            <span class="text-[10px] mono text-text-secondary/50 truncate italic">{item.file_path}</span>
                                        </div>
                                    </div>
                                    <div class="flex items-center gap-6 shrink-0">
                                        <div class="flex gap-1">
                                            {#each item.media_identifiers as media}
                                                <span class="text-[9px] font-black uppercase tracking-tighter bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded border border-blue-500/20">{media}</span>
                                            {/each}
                                        </div>
                                        <span class="text-xs font-bold mono text-text-secondary w-20 text-right">{formatSize(item.size)}</span>
                                        <button class="text-text-secondary hover:text-error-color opacity-0 group-hover:opacity-100 transition-all p-1" onclick={() => removeItem(item.id)}>
                                            <X size={16} />
                                        </button>
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </ScrollArea>
                </Card>
            </div>

            <!-- MANIFEST SIDEBAR -->
            <div class="flex flex-col gap-6">
                <!-- Recovery Destination Card -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl">
                    <h3 class="text-xs font-black uppercase tracking-widest text-text-primary mb-6 flex items-center gap-2">
                        <MapPin size={14} class="text-action-color" />
                        Recovery Destination
                    </h3>

                    <div class="space-y-4">
                        <div class="grid grid-cols-1 gap-2">
                            {#each restoreDests as dest}
                                <button
                                    class={cn(
                                        "flex items-center gap-3 p-3 rounded-lg border transition-all text-left group",
                                        selectedDest === dest
                                            ? "bg-action-color/10 border-action-color text-text-primary shadow-[0_0_15px_rgba(52,152,219,0.1)]"
                                            : "bg-bg-primary/50 border-border-color text-text-secondary hover:border-text-secondary/30"
                                    )}
                                    onclick={() => selectedDest = dest}
                                >
                                    <div class={cn(
                                        "w-2 h-2 rounded-full",
                                        selectedDest === dest ? "bg-action-color animate-pulse" : "bg-border-color"
                                    )}></div>
                                    <span class="text-[11px] font-bold mono truncate">{dest}</span>
                                </button>
                            {:else}
                                <div class="p-4 border-2 border-dashed border-border-color rounded-lg text-center">
                                    <p class="text-[10px] font-black uppercase tracking-widest text-text-secondary/50">No targets defined in settings</p>
                                </div>
                            {/each}
                        </div>
                        <p class="text-[9px] font-bold text-text-secondary/50 uppercase tracking-tight italic">Files will be extracted into this directory using their original folder structure.</p>
                    </div>
                </Card>

                <Card class="p-8 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-2xl relative overflow-hidden">
                    <div class="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                        <Database size={120} />
                    </div>

                    <div class="relative z-10">
                        <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-6 flex items-center gap-2">
                            <Info size={18} class="text-blue-500" />
                            Physical Manifest
                        </h3>

                        <div class="space-y-4">
                            {#if manifest}
                                {#each manifest.media_required as req}
                                    <div class="p-4 bg-bg-primary/50 border border-border-color rounded-xl flex items-center gap-4 group hover:border-blue-500/30 transition-colors">
                                        <div class={cn(
                                            "p-3 rounded-lg border shadow-inner",
                                            req.media_type === 'tape' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' : 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
                                        )}>
                                            {#if req.media_type === 'tape'}<CassetteTape size={20} />{:else}<HardDrive size={20} />{/if}
                                        </div>
                                        <div class="flex-1 min-w-0">
                                            <div class="flex justify-between items-center mb-1">
                                                <span class="text-sm font-black text-text-primary mono">{req.identifier}</span>
                                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary">{req.media_type}</span>
                                            </div>
                                            <div class="flex justify-between text-[10px] font-bold text-text-secondary opacity-60">
                                                <span>{req.file_count} FILES</span>
                                                <span>{formatSize(req.total_size)}</span>
                                            </div>
                                        </div>
                                    </div>
                                {/each}
                            {/if}
                        </div>

                        <div class="mt-8 p-4 bg-blue-500/5 border border-dashed border-blue-500/20 rounded-lg">
                            <p class="text-[10px] font-bold text-blue-300/70 leading-relaxed italic">
                                Note: Recovery will proceed sequentially by media to minimize hardware cycles.
                            </p>
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    {/if}
</div>
