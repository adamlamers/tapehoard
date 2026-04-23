<script lang="ts">
    import { onMount } from 'svelte';
    import {
        Play,
        Trash2,
        CassetteTape,
        ChevronRight,
        CheckCircle2,
        AlertCircle,
        Download,
        RotateCw,
        X,
        Search
    } from 'lucide-svelte';
    import { fade, fly } from 'svelte/transition';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import { browseIndexInventoryBrowseGet } from '$lib/api/sdk.gen';

    // Wizard State
    let currentStep = $state(1);

    // File Browser State
    let currentPath = $state('/');
    let indexedFiles = $state<FileItem[]>([]);
    let loading = $state(false);

    // Restore Cart (Selected Files)
    let restoreCart = $state<FileItem[]>([]);

    async function loadIndexedFiles(path: string) {
        loading = true;
        try {
            const response = await browseIndexInventoryBrowseGet({
                query: { path }
            });
            if (response.data) {
                // Map API response and preserve selection state if already in cart
                indexedFiles = response.data.map(f => ({
                    ...f,
                    type: f.type as 'file' | 'directory' | 'link',
                    selected: restoreCart.some(cartItem => cartItem.path === f.path)
                }));
            }
        } catch (error) {
            console.error("Failed to load indexed files:", error);
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        loadIndexedFiles(currentPath);
    });

    $effect(() => {
        if (currentPath) {
            loadIndexedFiles(currentPath);
        }
    });

    function handleToggleSelect(item: FileItem) {
        const index = restoreCart.findIndex(i => i.path === item.path);
        if (index > -1) {
            restoreCart = restoreCart.filter((_, i) => i !== index);
            item.selected = false;
        } else {
            restoreCart = [...restoreCart, { ...item, selected: true }];
            item.selected = true;
        }
    }

    function removeFromCart(path: string) {
        restoreCart = restoreCart.filter(i => i.path !== path);
        // Update selection in current view if visible
        const visibleItem = indexedFiles.find(f => f.path === path);
        if (visibleItem) visibleItem.selected = false;
    }

    const totalSize = $derived(restoreCart.reduce((acc, item) => acc + (item.size || 0), 0));
    const requiredMedia = $derived([...new Set(restoreCart.flatMap(item => item.media || []))]);

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

    function nextStep() {
        if (currentStep < 4) currentStep++;
    }

    function cancel() {
        currentStep = 1;
    }
</script>

<svelte:head>
    <title>Restore Wizard - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full">
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <RotateCw class="text-blue-500" size={28} />
                Restore Wizard
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Step {currentStep} of 4: {['Browse & Select', 'Insert Media', 'Swap Media', 'Finalize'][currentStep-1]}
            </p>
        </div>

        {#if currentStep === 1}
            <div class="flex gap-4 relative z-10">
                <Button variant="default" size="lg" class="px-8 h-12" disabled={restoreCart.length === 0} onclick={nextStep}>
                    <Play size={20} class="mr-2" />
                    Execute Restore
                </Button>
            </div>
        {/if}
    </header>

    {#if currentStep === 1}
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
            <!-- LEFT: VIRTUAL FILESYSTEM BROWSER -->
            <div class="lg:col-span-2 flex flex-col min-h-0 relative">
                <div class="mb-2 flex items-center justify-between">
                    <h3 class="text-sm font-bold uppercase tracking-widest text-text-secondary">Virtual Filesystem</h3>
                    <span class="text-[10px] bg-white/5 px-2 py-1 rounded text-text-secondary font-mono">Indexing: {currentPath}</span>
                </div>
                {#if loading}
                    <div class="absolute inset-0 bg-bg-primary/50 z-50 flex items-center justify-center top-8">
                        <span class="text-text-secondary animate-pulse">Querying Index...</span>
                    </div>
                {/if}
                <FileBrowser
                    bind:currentPath
                    files={indexedFiles}
                    mode="index"
                    onNavigate={(path) => currentPath = path}
                    onToggleTrack={handleToggleSelect}
                />
            </div>

            <!-- RIGHT: RESTORE CART -->
            <div class="flex flex-col gap-4 min-h-0">
                <div class="bg-bg-secondary border border-border-color rounded-xl p-6 flex flex-col h-full shadow-lg">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-lg font-black uppercase tracking-tight text-text-primary flex items-center gap-2">
                            <Download size={20} class="text-blue-400" />
                            Restore Cart
                        </h3>
                        <span class="bg-blue-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                            {restoreCart.length}
                        </span>
                    </div>

                    <div class="flex-1 overflow-y-auto mb-4 pr-2">
                        {#if restoreCart.length === 0}
                            <div class="h-full flex flex-col items-center justify-center text-center opacity-20 py-12">
                                <Search size={48} class="mb-4" />
                                <p class="text-xs font-bold uppercase tracking-widest leading-relaxed">
                                    Your cart is empty.<br>Select files from the index.
                                </p>
                            </div>
                        {:else}
                            <div class="flex flex-col gap-2">
                                {#each restoreCart as item}
                                    <div class="bg-bg-primary/50 border border-border-color/50 rounded-lg p-3 group transition-all hover:border-blue-500/30">
                                        <div class="flex justify-between items-start gap-2">
                                            <div class="min-w-0">
                                                <p class="text-[12px] font-bold text-text-primary truncate">{item.name}</p>
                                                <p class="text-[10px] text-text-secondary truncate mono opacity-50">{item.path}</p>
                                            </div>
                                            <button
                                                class="text-text-secondary hover:text-error-color transition-colors p-1"
                                                onclick={() => removeFromCart(item.path)}
                                            >
                                                <X size={14} />
                                            </button>
                                        </div>
                                        <div class="flex items-center gap-3 mt-2">
                                            <span class="text-[10px] mono text-text-secondary font-bold">{formatSize(item.size || 0)}</span>
                                            <div class="flex gap-1">
                                                {#each (item.media || []) as m}
                                                    <span class="flex items-center gap-1 text-[9px] bg-blue-500/10 text-blue-400 px-1 rounded font-bold">
                                                        <CassetteTape size={10} /> {m}
                                                    </span>
                                                {/each}
                                            </div>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                    </div>

                    <div class="pt-4 border-t border-border-color mt-auto">
                        <div class="flex justify-between mb-2">
                            <span class="text-[10px] font-bold uppercase tracking-widest text-text-secondary">Total Payload</span>
                            <span class="text-sm font-black text-text-primary mono">{formatSize(totalSize)}</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-[10px] font-bold uppercase tracking-widest text-text-secondary">Media Required</span>
                            <span class="text-sm font-black text-blue-400 mono">{requiredMedia.length} Tapes</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

    {:else if currentStep === 2}
        <!-- (Step 2-4 keep the same design as before but with Tailwind classes) -->
        <div in:fly={{ y: 20, duration: 300 }} class="flex flex-col items-center justify-center flex-1">
            <div class="bg-bg-secondary border-2 border-border-color rounded-2xl p-12 text-center shadow-2xl max-w-lg w-full">
                <div class="w-20 h-20 bg-blue-500/10 text-blue-500 rounded-full flex items-center justify-center mx-auto mb-6 animate-pulse">
                    <CassetteTape size={48} />
                </div>
                <h2 class="text-2xl font-black text-text-primary uppercase tracking-tight mb-2">Insert Tape</h2>
                <p class="text-text-secondary mb-8">
                    Please insert the following tape into the drive to begin extraction.
                </p>

                <div class="bg-bg-primary border-2 border-dashed border-border-color rounded-xl p-8 mb-8">
                    <span class="text-4xl font-black text-text-primary mono">{requiredMedia[0] || 'BUP-00001'}</span>
                </div>

                <div class="flex items-center justify-center gap-3 text-text-secondary text-sm font-bold uppercase tracking-widest mb-10">
                    <RotateCw size={18} class="animate-spin text-blue-500" />
                    <span>Waiting for drive status...</span>
                </div>

                <div class="flex gap-4 justify-center">
                    <Button variant="secondary" onclick={cancel}>
                        <X size={18} class="mr-2" /> Cancel
                    </Button>
                    <Button variant="default" onclick={nextStep}>
                        Simulate Load <ChevronRight size={18} class="ml-2" />
                    </Button>
                </div>
            </div>
        </div>
    {/if}
</div>
