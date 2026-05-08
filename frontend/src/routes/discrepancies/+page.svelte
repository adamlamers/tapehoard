<script lang="ts">
    import { onMount } from 'svelte';
    import { AlertTriangle, RotateCw, ShieldCheck, HardDriveDownload, Download, FileX } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import StatCard from '$lib/components/ui/StatCard.svelte';
    import EmptyState from '$lib/components/ui/EmptyState.svelte';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import { toast } from 'svelte-sonner';
    import {
        listDiscrepancies,
        batchResolveDiscrepancies,
        addFileToRestoreQueue,
        browseDiscrepancies,
        type DiscrepancySchema,
    } from '$lib/api';
    import { type FileItem } from '$lib/types';
    import { POLL_FAST } from '$lib/config';

    let discrepancies = $state<DiscrepancySchema[]>([]);
    let files = $state<FileItem[]>([]);
    let loading = $state(true);
    let currentPath = $state("ROOT");
    let selectedPaths = $state<Set<string>>(new Set());
    let batchLoading = $state(false);

    // Report modal state
    let showReport = $state(false);
    let reportData = $state<{
        recovered_count: number;
        lost_count: number;
        recovered_paths: string[];
        lost_paths: string[];
        message: string;
    } | null>(null);

    async function loadDiscrepancies() {
        loading = true;
        try {
            const response = await listDiscrepancies();
            if (response.data) {
                discrepancies = response.data;
            }
            await loadFiles(currentPath);
        } catch (error) {
            console.error("Failed to load discrepancies:", error);
            toast.error("Failed to load discrepancies");
        } finally {
            loading = false;
        }
    }

    async function loadFiles(path: string) {
        try {
            const response = await browseDiscrepancies({ query: { path } });
            if (response.data && (response.data as any).files) {
                files = (response.data as any).files.map((d: any) => {
                    // Check if it's a directory (has "type" property) or a file (has "id")
                    if (d.type === 'directory') {
                        // It's a directory
                        return {
                            name: d.name || d.path.split('/').pop() || d.path,
                            path: d.path,
                            type: 'directory',
                            discrepancy_count: d.discrepancy_count || 0
                        };
                    } else {
                        // It's a file (DiscrepancySchema)
                        return {
                            name: d.path.split('/').pop() || d.path,
                            path: d.path,
                            type: 'file',
                            size: d.size,
                            mtime: d.mtime ? new Date(d.mtime).getTime() / 1000 : undefined,
                            discrepancy_id: d.id,
                            is_deleted: d.is_deleted,
                            has_versions: d.has_versions,
                            ignored: false
                        };
                    }
                });
            }
        } catch (error) {
            console.error("Failed to browse discrepancies:", error);
        }
    }

    async function addToCart(item: FileItem) {
        if (!item.discrepancy_id) return;
        try {
            await addFileToRestoreQueue({
                path: { file_id: item.discrepancy_id }
            });
            toast.success("Added to restore cart");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to add to restore cart");
        }
    }

    async function batchResolve() {
        const ids = getDiscrepancyIdsFromPaths(selectedPaths);
        if (ids.length === 0) {
            toast.error("No files selected");
            return;
        }
        batchLoading = true;
        try {
            const response = await batchResolveDiscrepancies({
                body: { ids }
            });
            if (response.data) {
                reportData = response.data;
                showReport = true;
                selectedPaths = new Set();
                await loadDiscrepancies();
            }
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to resolve discrepancies");
        } finally {
            batchLoading = false;
        }
    }

    function downloadReport() {
        if (!reportData) return;
        const lines = [
            "TapeHoard Discrepancy Resolution Report",
            `Generated: ${new Date().toISOString()}`,
            "",
            `Recovered files (${reportData.recovered_count}):`,
            ...reportData.recovered_paths.map(p => `  [RECOVERABLE] ${p}`),
            "",
            `Permanently lost files (${reportData.lost_count}):`,
            ...reportData.lost_paths.map(p => `  [LOST] ${p}`),
            "",
            "End of report"
        ];
        const blob = new Blob([lines.join("\n")], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `discrepancy_report_${new Date().toISOString().split("T")[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function getDiscrepancyIdsFromPaths(paths: Set<string>): number[] {
        const ids: number[] = [];
        for (const d of discrepancies) {
            const path = d.path;
            if (paths.has(path)) {
                ids.push(d.id);
                continue;
            }
            // Check if this discrepancy is under a selected directory
            for (const selectedPath of paths) {
                if (path.startsWith(selectedPath + '/')) {
                    ids.push(d.id);
                    break;
                }
            }
        }
        return ids;
    }

    function getAffectedCounts(paths: Set<string>): { recoverable: number; lost: number } {
        let recoverable = 0;
        let lost = 0;
        for (const d of discrepancies) {
            const path = d.path;
            let isAffected = paths.has(path);
            if (!isAffected) {
                for (const selectedPath of paths) {
                    if (path.startsWith(selectedPath + '/')) {
                        isAffected = true;
                        break;
                    }
                }
            }
            if (isAffected) {
                if (d.has_versions) {
                    recoverable++;
                } else {
                    lost++;
                }
            }
        }
        return { recoverable, lost };
    }

    function navigateTo(path: string) {
        currentPath = path;
        loadFiles(path);
    }

    const missingItems = $derived(discrepancies.filter(d => d.is_deleted));
    const pendingItems = $derived(discrepancies.filter(d => !d.is_deleted));

    // Statistics
    const missingWithNoBackup = $derived(
        discrepancies.filter(d => d.is_deleted && !d.has_versions).length
    );
    const missingWithBackup = $derived(
        discrepancies.filter(d => d.is_deleted && d.has_versions).length
    );

    onMount(loadDiscrepancies);
</script>

<svelte:head>
    <title>Discrepancies - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 h-full animate-in fade-in duration-700">
    <PageHeader
        title="Discrepancies"
        description="Files missing from disk or confirmed deleted"
        icon={AlertTriangle}
    >
        {#snippet actions()}
            <div class="flex items-center gap-2 px-3 py-1.5 bg-bg-primary/50 rounded-lg border border-border-color shadow-inner">
                <div class="w-2 h-2 rounded-full {discrepancies.length > 0 ? 'bg-error-color animate-pulse' : 'opacity-20 bg-text-secondary'}"></div>
                <span class="text-[10px] font-medium text-text-secondary uppercase tracking-wider">
                    {discrepancies.length} found
                </span>
            </div>
            <Button variant="outline" size="icon" onclick={loadDiscrepancies} disabled={loading}>
                <RotateCw size={16} class={loading ? 'animate-spin' : ''} />
            </Button>
        {/snippet}
    </PageHeader>

    {#if loading && discrepancies.length === 0}
        <div class="grid grid-cols-2 gap-3">
            <div class="h-20 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
            <div class="h-20 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
        </div>
        <div class="h-64 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
    {:else if discrepancies.length === 0}
        <EmptyState
            icon={ShieldCheck}
            title="All clear"
            description="No discrepancies detected. All tracked files are present on disk."
        />
    {:else}
        <!-- Summary Statistics -->
        <div class="grid grid-cols-2 gap-3 shrink-0">
            <StatCard
                label="Missing with no backup"
                value={missingWithNoBackup}
                subLabel="Files missing from disk with no copies on archive media"
                variant="error"
            />
            <StatCard
                label="Missing with backup"
                value={missingWithBackup}
                subLabel="Files missing from disk but have copies on archive media"
                variant="warning"
            />
        </div>

        <!-- Batch Actions Bar -->
        {#if selectedPaths.size > 0}
            {@const { recoverable: recoverableCount, lost: lostCount } = getAffectedCounts(selectedPaths)}
            <div class="flex items-center gap-3 p-3 bg-bg-tertiary/50 rounded-lg border border-border-color">
                <div class="flex flex-col text-sm text-text-secondary">
                    <span>{selectedPaths.size} item(s) selected</span>
                    {#if recoverableCount > 0 && lostCount > 0}
                        <span class="text-xs opacity-60">{recoverableCount} recoverable, {lostCount} lost forever</span>
                    {:else if recoverableCount > 0}
                        <span class="text-xs opacity-60">All {recoverableCount} file(s) can be recovered</span>
                    {:else if lostCount > 0}
                        <span class="text-xs opacity-60">All {lostCount} file(s) are lost forever</span>
                    {/if}
                </div>
                <div class="flex gap-2 ml-auto">
                    <Button size="sm" variant="default" onclick={batchResolve} disabled={batchLoading}>
                        {#if batchLoading}
                            <RotateCw size={14} class="mr-1 animate-spin" /> Resolving...
                        {:else if recoverableCount > 0 && lostCount > 0}
                            <HardDriveDownload size={14} class="mr-1" />
                            Recover {recoverableCount}, confirm {lostCount} lost
                        {:else if recoverableCount > 0}
                            <HardDriveDownload size={14} class="mr-1" />
                            Add {recoverableCount} to restore queue
                        {:else}
                            <FileX size={14} class="mr-1" />
                            Confirm {lostCount} as deleted
                        {/if}
                    </Button>
                </div>
            </div>
        {/if}

        <!-- FileBrowser Component in discrepancies mode -->
        <div class="flex-1 min-h-[600px] bg-bg-secondary border border-border-color shadow-2xl rounded-lg flex flex-col relative overflow-hidden">
            <FileBrowser
                bind:currentPath={currentPath}
                bind:selectedPaths={selectedPaths}
                files={files}
                mode="discrepancies"
                onNavigate={navigateTo}
                onAddToCart={addToCart}
            />
        </div>
    {/if}
</div>

<!-- Resolution Report Modal -->
{#if showReport && reportData}
    <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        onmousedown={() => showReport = false}
        role="presentation"
    >
        <div
            class="bg-bg-secondary border border-border-color rounded-xl shadow-2xl max-w-2xl w-full mx-4 overflow-hidden"
            onmousedown={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="report-title"
            tabindex="-1"
        >
            <div class="p-5 border-b border-border-color">
                <h3 id="report-title" class="text-lg font-semibold">Resolution Report</h3>
                <p class="text-sm text-text-secondary mt-1">Results of the batch discrepancy resolution</p>
            </div>
            <div class="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
                {#if reportData.recovered_count > 0}
                    <div class="space-y-2">
                        <div class="flex items-center gap-2 text-success-color">
                            <HardDriveDownload size={16} />
                            <span class="font-medium">{reportData.recovered_count} file(s) queued for recovery</span>
                        </div>
                        <ul class="text-sm text-text-secondary space-y-1 pl-6">
                            {#each reportData.recovered_paths as path}
                                <li class="truncate">{path}</li>
                            {/each}
                        </ul>
                    </div>
                {/if}
                {#if reportData.lost_count > 0}
                    <div class="space-y-2">
                        <div class="flex items-center gap-2 text-error-color">
                            <FileX size={16} />
                            <span class="font-medium">{reportData.lost_count} file(s) confirmed as permanently lost</span>
                        </div>
                        <ul class="text-sm text-text-secondary space-y-1 pl-6">
                            {#each reportData.lost_paths as path}
                                <li class="truncate">{path}</li>
                            {/each}
                        </ul>
                    </div>
                {/if}
            </div>
            <div class="p-5 border-t border-border-color flex gap-3">
                <Button variant="outline" class="flex-1" onclick={downloadReport}>
                    <Download size={14} class="mr-2" />
                    Download Report
                </Button>
                <Button class="flex-1" onclick={() => showReport = false}>
                    Done
                </Button>
            </div>
        </div>
    </div>
{/if}
