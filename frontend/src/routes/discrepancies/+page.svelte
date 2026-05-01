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
        browseDiscrepanciesGet,
        getDiscrepanciesTreeGet,
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
                // Convert discrepancies to FileItem format for FileBrowser
                files = response.data.map((d: DiscrepancySchema) => ({
                    name: d.path.split('/').pop() || d.path,
                    path: d.path,
                    type: 'file',
                    size: d.size,
                    mtime: d.mtime ? new Date(d.mtime).getTime() / 1000 : undefined,
                    discrepancy_id: d.id,
                    is_deleted: d.is_deleted,
                    has_versions: d.has_versions,
                    ignored: false
                }));
            }
        } catch (error) {
            console.error("Failed to load discrepancies:", error);
            toast.error("Failed to load discrepancies");
        } finally {
            loading = false;
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

    async function navigateTo(path: string) {
        currentPath = path;
    }

    const missingItems = $derived(discrepancies.filter(d => d.is_deleted));
    const pendingItems = $derived(discrepancies.filter(d => !d.is_deleted));

    onMount(loadDiscrepancies);
</script>

<svelte:head>
    <title>Discrepancies - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 flex-1 min-h-0 animate-in fade-in duration-700">
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
            <StatCard label="Missing from disk" value={missingItems.length} subLabel="Files the scanner did not find" variant="error" />
            <StatCard label="Pending confirmation" value={pendingItems.length} subLabel="Tracked files not yet confirmed" variant="warning" />
        </div>

        <!-- FileBrowser Component in discrepancies mode -->
        <div class="flex-1 min-h-0 overflow-hidden">
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
