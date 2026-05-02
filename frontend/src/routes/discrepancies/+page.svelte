<script lang="ts">
    import { onMount } from 'svelte';
    import { AlertTriangle, RotateCw, ShieldCheck, HardDriveDownload } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import StatCard from '$lib/components/ui/StatCard.svelte';
    import EmptyState from '$lib/components/ui/EmptyState.svelte';
    import FileBrowser from '$lib/components/file-browser/FileBrowser.svelte';
    import { toast } from 'svelte-sonner';
    import {
        listDiscrepanciesSystemDiscrepanciesGet,
        dismissDiscrepancySystemDiscrepanciesFileIdDismissPost,
        batchDismissSystemDiscrepanciesBatchDismissPost,
        batchHardDeleteSystemDiscrepanciesBatchDeletePost,
        addFileToRecoveryQueueRestoresQueueFileFileIdPost,
        batchAddToRecoveryQueueRestoresQueueBatchPost,
        browseDiscrepanciesSystemDiscrepanciesBrowseGet,
        getDiscrepanciesTreeSystemDiscrepanciesTreeGet,
        type DiscrepancySchema,
    } from '$lib/api';
    import { type FileItem } from '$lib/types';
    import { POLL_FAST } from '$lib/config';

    let discrepancies = $state<DiscrepancySchema[]>([]);
    let files = $state<FileItem[]>([]);
    let loading = $state(true);
    let currentPath = $state("ROOT");
    let selectedIds = $state<Set<number>>(new Set());
    let batchAction = $state<'acknowledge' | 'recover' | null>(null);
    let batchLoading = $state(false);

    async function loadDiscrepancies() {
        loading = true;
        try {
            const response = await listDiscrepanciesSystemDiscrepanciesGet();
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
            const response = await browseDiscrepanciesSystemDiscrepanciesBrowseGet({ query: { path } });
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

    async function undoDismiss(item: FileItem) {
        if (!item.discrepancy_id) return;
        try {
            await dismissDiscrepancySystemDiscrepanciesFileIdDismissPost({
                path: { file_id: item.discrepancy_id }
            });
            toast.success("Dismissal undone");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to undo dismiss");
        }
    }

    async function deletePermanently(item: FileItem) {
        if (!item.discrepancy_id) return;
        try {
            await batchHardDeleteSystemDiscrepanciesBatchDeletePost({
                body: { ids: [item.discrepancy_id] }
            });
            toast.success("File record deleted permanently");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to delete file record");
        }
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

        <!-- FileBrowser Component in discrepancies mode -->
        <div class="flex-1 min-h-[600px] bg-bg-secondary border border-border-color shadow-2xl rounded-lg flex flex-col relative overflow-hidden">
            <FileBrowser
                bind:currentPath={currentPath}
                files={files}
                mode="discrepancies"
                onNavigate={navigateTo}
                onUndoDismiss={undoDismiss}
                onDelete={deletePermanently}
            />
        </div>
    {/if}
</div>
