<script lang="ts">
    import { onMount } from 'svelte';
    import { Save, PlayCircle, FolderTree, FileCheck, Database, HardDrive, LayoutGrid, RotateCw, Search } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import { browsePathSystemBrowseGet, trackBatchSystemTrackBatchPost } from '$lib/api/sdk.gen';
    import { toast } from "svelte-sonner";
    import { cn } from "$lib/utils";

    // Current directory state
    let currentPath = $state('/source_data');
    let files = $state<FileItem[]>([]);
    let loading = $state(false);
    let committing = $state(false);

    // Staging area for tracking changes: path -> desired tracked state
    let pendingChanges = $state<Map<string, boolean>>(new Map());

    async function loadFiles(path: string) {
        loading = true;
        try {
            const response = await browsePathSystemBrowseGet({
                query: { path }
            });
            if (response.data) {
                files = response.data.map(f => ({
                    ...f,
                    type: f.type as 'file' | 'directory' | 'link'
                }));
            }
        } catch (error) {
            console.error("Failed to load files:", error);
            toast.error("Failed to load file system");
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        loadFiles(currentPath);
    });

    $effect(() => {
        if (currentPath) {
            loadFiles(currentPath);
        }
    });

    function handleNavigate(path: string) {
        currentPath = path;
    }

    // Toggle track locally (staging)
    function handleToggleTrack(item: FileItem) {
        const path = item.path;
        const currentlyTracked = item.tracked;
        const stagedState = pendingChanges.get(path);

        if (stagedState !== undefined) {
            // If already staged, revert to original state if toggled back
            if (stagedState === !currentlyTracked) {
                pendingChanges.delete(path);
                pendingChanges = new Map(pendingChanges); // Trigger reactivity
            } else {
                pendingChanges.set(path, !stagedState);
                pendingChanges = new Map(pendingChanges);
            }
        } else {
            // Stage the flip
            pendingChanges.set(path, !currentlyTracked);
            pendingChanges = new Map(pendingChanges);
        }
    }

    // Computed files that merge original state with pending changes
    const displayFiles = $derived(files.map(f => {
        const pending = pendingChanges.get(f.path);
        return {
            ...f,
            tracked: pending !== undefined ? pending : f.tracked
        };
    }));

    const hasChanges = $derived(pendingChanges.size > 0);

    async function commitChanges() {
        if (!hasChanges) return;

        committing = true;
        const tracks: string[] = [];
        const untracks: string[] = [];

        for (const [path, track] of pendingChanges.entries()) {
            if (track) tracks.push(path);
            else untracks.push(path);
        }

        const promise = (async () => {
            await trackBatchSystemTrackBatchPost({
                body: { tracks, untracks }
            });
            pendingChanges = new Map();
            await loadFiles(currentPath);
        })();

        toast.promise(promise, {
            loading: 'Committing changes...',
            success: 'Tracking updated successfully',
            error: 'Failed to update tracking'
        });

        try {
            await promise;
        } catch (e) {
            console.error(e);
        } finally {
            committing = false;
        }
    }
</script>

<svelte:head>
    <title>File Tracking - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full">
    <!-- INTEGRATED HEADER -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-action-color/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <FolderTree class="text-action-color" size={28} />
                File Tracking
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Data Provisioning & Indexing Configuration
            </p>
        </div>

        <div class="flex gap-4 relative z-10">
            <Button variant="secondary" size="lg" class="px-6 h-12 border-border-color font-bold uppercase tracking-widest text-[11px]">
                <PlayCircle size={20} class="mr-2 text-action-color" />
                Simulate Scan
            </Button>
            <Button
                variant="default"
                size="lg"
                class={cn(
                    "px-8 h-12 font-bold uppercase tracking-widest text-[11px] transition-all",
                    hasChanges ? "bg-action-color text-white shadow-lg shadow-action-color/20" : "opacity-50"
                )}
                onclick={commitChanges}
                disabled={!hasChanges || committing}
            >
                {#if committing}
                    <RotateCw size={20} class="mr-2 animate-spin" />
                {:else}
                    <Save size={20} class="mr-2" />
                {/if}
                Commit Changes ({pendingChanges.size})
            </Button>
        </div>
    </header>

    <!-- BACKUP DELTA STATS (FULL WIDTH) -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-action-color/10 rounded-lg text-action-color border border-action-color/20">
                <LayoutGrid size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Tracked Items</span>
                <span class="text-xl font-black text-text-primary mono">14,203</span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-action-color/10 rounded-lg text-action-color border border-action-color/20">
                <Database size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Est. Payload</span>
                <span class="text-xl font-black text-action-color mono">4.2 TB</span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-success-color/10 rounded-lg text-success-color border border-success-color/20">
                <HardDrive size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Media Load</span>
                <span class="text-xl font-black text-success-color mono">2 x LTO-6</span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-orange-500/10 rounded-lg text-orange-500 border border-orange-500/20">
                <FileCheck size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Last Simulation</span>
                <span class="text-xl font-black text-text-primary mono">2h ago</span>
            </div>
        </Card>
    </div>

    <!-- FULL WIDTH FILE BROWSER -->
    <div class="flex-1 min-h-0 relative">
        {#if loading}
            <div class="absolute inset-0 bg-bg-primary/50 z-50 flex items-center justify-center rounded-lg">
                <div class="flex flex-col items-center gap-3">
                    <RotateCw size={32} class="animate-spin text-action-color" />
                    <span class="text-[11px] font-black uppercase tracking-widest text-text-secondary">Accessing File System...</span>
                </div>
            </div>
        {/if}
        <FileBrowser
            bind:currentPath
            files={displayFiles}
            onNavigate={handleNavigate}
            onToggleTrack={handleToggleTrack}
        />
    </div>
</div>
