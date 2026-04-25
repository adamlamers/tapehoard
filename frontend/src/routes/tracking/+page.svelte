<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Save, FolderTree, Database, HardDrive, LayoutGrid, RotateCw, Activity, FileCheck } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        browsePathSystemBrowseGet,
        trackBatchSystemTrackBatchPost,
        triggerScanSystemScanPost,
        getScanStatusSystemScanStatusGet,
        searchSystemSystemSearchGet,
        type ScanStatusSchema
    } from '$lib/api';
    import { toast } from "svelte-sonner";
    import { cn } from "$lib/utils";

    // Current directory state
    let currentPath = $state('ROOT');
    let searchQuery = $state('');
    let files = $state<FileItem[]>([]);
    let loading = $state(false);
    let searchLoading = $state(false);
    let committing = $state(false);

    // Scanner Status (local for button state only)
    let scanRunning = $state(false);
    let pollInterval: any;
    let searchTimeout: any;

    // Staging area for tracking changes: path -> desired tracked state
    let pendingChanges = $state<Map<string, boolean>>(new Map());

    async function loadFiles(path: string) {
        if (searchQuery.trim().length >= 3) return; // Prevent loading path if searching
        loading = true;
        try {
            const response = await browsePathSystemBrowseGet({
                query: { path }
            });
            if (response.data) {
                files = response.data.map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    tracked: f.tracked ?? false,
                    ignored: f.ignored ?? false,
                    sha256_hash: null // Not returned in browse but kept for state consistency
                }));
            }
        } catch (error) {
            console.error("Failed to load files:", error);
            toast.error("Failed to load file system");
        } finally {
            loading = false;
        }
    }

    async function searchFiles(query: string) {
        searchLoading = true;
        try {
            const response = await searchSystemSystemSearchGet({
                query: { q: query }
            });
            if (response.data) {
                files = response.data.map(f => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    tracked: f.tracked ?? false,
                    ignored: f.ignored ?? false,
                    sha256_hash: null
                }));
            }
        } catch (error) {
            console.error("Failed to search files:", error);
            toast.error("Search failed");
        } finally {
            searchLoading = false;
        }
    }

    $effect(() => {
        const query = searchQuery.trim();
        if (searchTimeout) clearTimeout(searchTimeout);

        if (query.length >= 3) {
            searchTimeout = setTimeout(() => {
                searchFiles(query);
            }, 300);
        } else if (query.length === 0) {
            // Wait slightly so we don't immediately fetch while user is deleting text rapidly
            searchTimeout = setTimeout(() => {
                loadFiles(currentPath);
            }, 50);
        }
    });

    async function updateScanStatus() {
        try {
            const response = await getScanStatusSystemScanStatusGet();
            if (response.data) {
                const wasRunning = scanRunning;
                scanRunning = response.data.is_running;

                if (wasRunning && !scanRunning) {
                    loadFiles(currentPath);
                }
            }
        } catch (error) {
            console.error("Failed to get scan status:", error);
        }
    }

    async function startScan() {
        try {
            await triggerScanSystemScanPost();
            updateScanStatus();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start scan");
        }
    }

    onMount(() => {
        loadFiles(currentPath);
        updateScanStatus();
        pollInterval = setInterval(updateScanStatus, 2000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    $effect(() => {
        if (currentPath) {
            loadFiles(currentPath);
        }
    });

    function handleNavigate(path: string) {
        currentPath = path;
    }

    function handleToggleTrack(item: FileItem) {
        const path = item.path;
        const currentlyTracked = item.tracked || false;
        const stagedState = pendingChanges.get(path);

        if (stagedState !== undefined) {
            if (stagedState === !currentlyTracked) {
                pendingChanges.delete(path);
                pendingChanges = new Map(pendingChanges);
            } else {
                pendingChanges.set(path, !stagedState);
                pendingChanges = new Map(pendingChanges);
            }
        } else {
            pendingChanges.set(path, !currentlyTracked);
            pendingChanges = new Map(pendingChanges);
        }
    }

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
                Tracking Policy
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Data Provisioning & Indexing Configuration
            </p>
        </div>

        <div class="flex gap-4 relative z-10">
            <Button
                variant="secondary"
                size="lg"
                class="px-6 h-12 border-border-color font-bold uppercase tracking-widest text-[11px]"
                onclick={startScan}
                disabled={scanRunning}
            >
                {#if scanRunning}
                    <RotateCw size={20} class="mr-2 animate-spin text-action-color" />
                    Scanning...
                {:else}
                    <Activity size={20} class="mr-2 text-action-color" />
                    Run Scanner
                {/if}
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
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Selection Set</span>
                <span class="text-xl font-black text-text-primary mono">
                    {files.filter(f => f.tracked).length}
                </span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-action-color/10 rounded-lg text-action-color border border-action-color/20">
                <Database size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Directory Index</span>
                <span class="text-xl font-black text-action-color mono">
                    {files.length}
                </span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-success-color/10 rounded-lg text-success-color border border-success-color/20">
                <HardDrive size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Tracked Files</span>
                <span class="text-xl font-black text-success-color mono">
                    {files.filter(f => !f.ignored).length}
                </span>
            </div>
        </Card>

        <Card class="bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color shadow-lg p-4 flex items-center gap-4">
            <div class="p-3 bg-orange-500/10 rounded-lg text-orange-500 border border-orange-500/20">
                <FileCheck size={24} />
            </div>
            <div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Pending Actions</span>
                <span class="text-xl font-black text-text-primary mono">
                    {pendingChanges.size}
                </span>
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
            bind:searchQuery
            files={displayFiles}
            isSearching={searchLoading}
            onNavigate={handleNavigate}
            onToggleTrack={handleToggleTrack}
        />    </div>
</div>
