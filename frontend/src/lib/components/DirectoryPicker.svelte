<script lang="ts">
    import { Folder, ChevronRight, Home, ArrowLeft, Check, X, RotateCw } from 'lucide-svelte';
    import { Button } from './ui/button';
    import { listDirectories } from '$lib/api';
    import { cn } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let { onSelect, onCancel } = $props<{
        onSelect: (path: string) => void;
        onCancel: () => void;
    }>();

    let currentPath = $state("/");
    let directories = $state<{name: string, path: string}[]>([]);
    let loading = $state(false);

    async function loadDirectories(path: string) {
        loading = true;
        try {
            const response = await listDirectories({
                query: { path }
            });
            if (response.data) {
                directories = response.data as any[];
                currentPath = path;
            }
        } catch (error) {
            toast.error("Failed to access directory");
        } finally {
            loading = false;
        }
    }

    function navigateUp() {
        const parts = currentPath.split("/").filter(Boolean);
        if (parts.length === 0) return;
        const parent = "/" + parts.slice(0, -1).join("/");
        loadDirectories(parent);
    }

    function selectCurrent() {
        onSelect(currentPath);
    }

    $effect(() => {
        loadDirectories(currentPath);
    });
</script>

<div class="fixed inset-0 z-[1100] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6 animate-in fade-in duration-300">
    <div class="w-[500px] max-h-[80vh] bg-bg-secondary border border-border-color shadow-2xl rounded-2xl overflow-hidden flex flex-col">
        <header class="p-6 border-b border-border-color bg-bg-tertiary/30">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-black uppercase tracking-tight text-text-primary flex items-center gap-2">
                    <Folder size={20} class="text-blue-500" />
                    Select Directory
                </h3>
                <Button variant="ghost" size="icon" onclick={onCancel}><X size={20} /></Button>
            </div>

            <div class="flex items-center gap-2 bg-bg-primary p-3 rounded-lg border border-border-color/50 mono text-xs text-text-secondary overflow-x-auto whitespace-nowrap scrollbar-hide">
                <Home size={14} class="shrink-0" />
                <span>{currentPath}</span>
            </div>
        </header>

        <div class="flex-1 overflow-y-auto p-4 space-y-1">
            {#if currentPath !== "/"}
                <button
                    class="w-full flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-white/5 text-left transition-colors text-text-secondary group"
                    onclick={navigateUp}
                >
                    <ArrowLeft size={16} class="group-hover:-translate-x-1 transition-transform" />
                    <span class="text-sm font-bold uppercase tracking-widest text-3xs">Go Up</span>
                </button>
            {/if}

            {#each directories as dir}
                <button
                    class="w-full flex items-center justify-between px-4 py-3 rounded-lg hover:bg-white/5 text-left transition-colors group border border-transparent hover:border-border-color/30"
                    onclick={() => loadDirectories(dir.path)}
                >
                    <div class="flex items-center gap-3 overflow-hidden">
                        <Folder size={16} class="text-blue-500/60 shrink-0" />
                        <span class="text-sm font-medium truncate text-text-primary">{dir.name}</span>
                    </div>
                    <ChevronRight size={14} class="text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity" />
                </button>
            {:else}
                {#if !loading}
                    <div class="py-12 text-center opacity-30">
                        <Folder size={32} class="mx-auto mb-2" />
                        <p class="text-3xs font-black uppercase tracking-widest">No Subdirectories</p>
                    </div>
                {/if}
            {/each}

            {#if loading}
                <div class="py-12 flex justify-center">
                    <RotateCw size={24} class="animate-spin text-blue-500/50" />
                </div>
            {/if}
        </div>

        <footer class="p-6 bg-bg-tertiary/20 border-t border-border-color flex gap-3">
            <Button variant="outline" class="flex-1 h-12 font-black uppercase tracking-widest text-2xs" onclick={onCancel}>Cancel</Button>
            <Button variant="default" class="flex-[2] h-12 font-black uppercase tracking-widest text-2xs" onclick={selectCurrent}>
                <Check size={18} class="mr-2" /> Select This Folder
            </Button>
        </footer>
    </div>
</div>
