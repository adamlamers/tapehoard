<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Save, FolderTree, Database, HardDrive, LayoutGrid, RotateCw, Activity, FileCheck, ArrowRight } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card } from '$lib/components/ui/card';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import type { FileItem } from '$lib/types';
    import {
        browseSystemPathSystemBrowseGet,
        batchUpdateTrackingSystemTrackBatchPost,
        triggerScanSystemScanPost,
        getScanStatusSystemScanStatusGet,
        searchSystemIndexSystemSearchGet,
        type ScanStatusSchema
    } from '$lib/api';
    import { toast } from "svelte-sonner";
    import { cn } from "$lib/utils";
    import { page } from '$app/state';

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
            const response = await browseSystemPathSystemBrowseGet({
                query: { path }
            });
            if (response.data) {
                files = response.data.map((f: any) => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    ignored: f.ignored ?? false,
                    sha256_hash: f.sha256_hash ?? null
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
            const response = await searchSystemIndexSystemSearchGet({
                query: { q: query, path: currentPath }
            });
            if (response.data) {
                files = response.data.map((f: any) => ({
                    name: f.name,
                    path: f.path,
                    type: f.type as 'file' | 'directory' | 'link',
                    size: f.size ?? null,
                    mtime: f.mtime ?? null,
                    ignored: f.ignored ?? false,
                    sha256_hash: f.sha256_hash ?? null
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
        const path = currentPath;
        const query = searchQuery.trim();
        if (searchTimeout) clearTimeout(searchTimeout);

        if (query.length >= 3) {
            searchTimeout = setTimeout(() => {
                searchFiles(query);
            }, 300);
        } else {
            // If query is empty or too short, load the current directory
            // We use a small timeout to debounce rapid navigation or clearing
            searchTimeout = setTimeout(() => {
                loadFiles(path);
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

    onMount(async () => {
        // Handle deep-linked path from query params (e.g., from insights treemap)
        const targetPath = page.url.searchParams.get('path');
        if (targetPath) {
            currentPath = targetPath;
        }

        await loadFiles(currentPath);
        await updateScanStatus();
        pollInterval = setInterval(updateScanStatus, 3000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    function handleNavigate(path: string) {
        currentPath = path;
    }

    function handleToggleTrack(item: FileItem) {
        const path = item.path;
        const currentIgnored = item.ignored;
        const staged = pendingChanges.get(path);

        if (staged !== undefined) {
            pendingChanges.delete(path);
        } else {
            // If currently ignored, stage it for UN-ignoring (tracking)
            // If currently NOT ignored, stage it for ignoring (untracking)
            pendingChanges.set(path, !currentIgnored);
        }

        // Trigger reactivity for Svelte 5 state
        pendingChanges = new Map(pendingChanges);
    }

    async function commitChanges() {
        if (pendingChanges.size === 0) return;
        committing = true;
        try {
            // A staged value of FALSE means 'is_ignored = false' -> track it
            // A staged value of TRUE means 'is_ignored = true' -> untrack it
            const tracks = Array.from(pendingChanges.entries())
                .filter(([_, ignoredState]) => !ignoredState)
                .map(([path, _]) => path);
            const untracks = Array.from(pendingChanges.entries())
                .filter(([_, ignoredState]) => ignoredState)
                .map(([path, _]) => path);

            await batchUpdateTrackingSystemTrackBatchPost({
                body: { tracks, untracks }
            });
            pendingChanges.clear();
            pendingChanges = new Map(); // Trigger reactivity
            await loadFiles(currentPath);
            toast.success("Changes committed to index");
        } catch (error) {
            toast.error("Failed to update tracking");
        } finally {
            committing = false;
        }
    }

    const hasChanges = $derived(pendingChanges.size > 0);
</script>

<svelte:head>
    <title>Live Filesystem - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 h-full animate-in fade-in duration-700">
    <header class="flex justify-between items-start bg-bg-secondary px-8 py-6 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <FolderTree class="text-blue-500" size={28} />
                Live Filesystem
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Define backup rules & browse physical storage
            </p>
        </div>

        <div class="flex items-center gap-3 relative z-10">
            {#if hasChanges}
                <div class="mr-4 px-4 py-2 bg-blue-500/10 border border-blue-500/30 rounded-lg animate-pulse">
                    <span class="text-[10px] font-black text-blue-400 uppercase tracking-[0.2em]">{pendingChanges.size} Pending Changes</span>
                </div>
            {/if}
            <Button
                variant={hasChanges ? "default" : "outline"}
                class={cn("h-11 px-6 font-black uppercase tracking-widest text-[10px] transition-all duration-500 shadow-lg",
                    hasChanges ? "bg-blue-600 hover:bg-blue-700 border-none scale-105" : "border-border-color opacity-50")}
                onclick={commitChanges}
                disabled={!hasChanges || committing}
            >
                <Save size={16} class="mr-2" />
                {committing ? 'Committing...' : 'Commit Rules'}
            </Button>
            <Button
                variant="outline"
                class={cn("h-11 px-6 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-blue-500/30 transition-all",
                    scanRunning && "text-blue-500 border-blue-500/20 bg-blue-500/5")}
                onclick={startScan}
                disabled={scanRunning}
            >
                {#if scanRunning}
                    <RotateCw size={16} class="mr-2 animate-spin" />
                    Scanning...
                {:else}
                    <Activity size={16} class="mr-2" />
                    Quick Scan
                {/if}
            </Button>
        </div>
    </header>

    <Card class="flex-1 min-h-[600px] bg-bg-secondary border-border-color shadow-2xl flex flex-col relative overflow-hidden">
        <div class="flex-1 flex flex-col min-h-0">
            <FileBrowser
                {files}
                bind:currentPath
                isSearching={searchLoading}
                bind:searchQuery
                onNavigate={handleNavigate}
                onToggleTrack={handleToggleTrack}
                {pendingChanges}
                mode="live"
            />
        </div>
    </Card>
</div>
