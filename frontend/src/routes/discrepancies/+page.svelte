<script lang="ts">
    import { onMount } from 'svelte';
    import {
        AlertTriangle,
        FileX,
        FileQuestion,
        RotateCw,
        Check,
        ShieldCheck,
        EyeOff,
        FolderOpen,
        X,
        ChevronDown,
        ChevronRight,
        HardDriveDownload
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import { Card } from '$lib/components/ui/card';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import StatCard from '$lib/components/ui/StatCard.svelte';
    import EmptyState from '$lib/components/ui/EmptyState.svelte';
    import { cn, formatLocalDate } from '$lib/utils';
    import { toast } from 'svelte-sonner';
    import {
        listDiscrepanciesSystemDiscrepanciesGet,
        dismissDiscrepancySystemDiscrepanciesFileIdDismissPost,
        batchDismissSystemDiscrepanciesBatchDismissPost,
        batchHardDeleteSystemDiscrepanciesBatchDeletePost,
        addFileToRecoveryQueueRestoresQueueFileFileIdPost,
        batchAddToRecoveryQueueRestoresQueueBatchPost,
        type DiscrepancySchema
    } from '$lib/api';

    interface GroupedItem {
        directory: string;
        items: DiscrepancySchema[];
    }

    let discrepancies = $state<DiscrepancySchema[]>([]);
    let loading = $state(true);
    let acknowledging = $state<number | null>(null);
    let recovering = $state<number | null>(null);
    let selectedIds = $state<Set<number>>(new Set());
    let batchAction = $state<'acknowledge' | 'recover' | null>(null);
    let batchLoading = $state(false);
    let collapsedDirs = $state<Record<string, boolean>>({});

    function toggleCollapse(dir: string) {
        collapsedDirs[dir] = !collapsedDirs[dir];
    }

    const groupedItems = $derived.by(() => {
        collapsedDirs;
        const map = new Map<string, DiscrepancySchema[]>();
        for (const d of discrepancies) {
            const parts = d.path.split('/');
            const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '/';
            if (!map.has(dir)) map.set(dir, []);
            map.get(dir)!.push(d);
        }
        const result: GroupedItem[] = [];
        for (const [dir, items] of map) {
            result.push({ directory: dir, items });
        }
        result.sort((a, b) => a.directory.localeCompare(b.directory));
        return result;
    });

    async function loadDiscrepancies() {
        loading = true;
        try {
            const response = await listDiscrepanciesSystemDiscrepanciesGet();
            if (response.data) {
                discrepancies = response.data;
            }
        } catch (error) {
            console.error("Failed to load discrepancies:", error);
            toast.error("Failed to load discrepancies");
        } finally {
            loading = false;
        }
    }

    async function acknowledgeLoss(id: number) {
        acknowledging = id;
        try {
            await dismissDiscrepancySystemDiscrepanciesFileIdDismissPost({
                path: { file_id: id }
            });
            toast.success("Loss acknowledged");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to acknowledge loss");
        } finally {
            acknowledging = null;
        }
    }

    async function addToRecoveryQueue(id: number) {
        recovering = id;
        try {
            await addFileToRecoveryQueueRestoresQueueFileFileIdPost({
                path: { file_id: id }
            });
            toast.success("Added to recovery queue");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to add to recovery queue");
        } finally {
            recovering = null;
        }
    }

    async function executeBatchAction() {
        if (!batchAction || selectedIds.size === 0) return;
        batchLoading = true;
        const ids = Array.from(selectedIds);
        try {
            if (batchAction === 'recover') {
                await batchAddToRecoveryQueueRestoresQueueBatchPost({
                    body: { ids }
                });
                toast.success(`${selectedIds.size} file(s) added to recovery queue`);
            } else if (batchAction === 'acknowledge') {
                await batchDismissSystemDiscrepanciesBatchDismissPost({
                    body: { ids }
                });
                toast.success(`${selectedIds.size} file(s) acknowledged as lost`);
            }
            selectedIds = new Set();
            batchAction = null;
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Batch action failed");
        } finally {
            batchLoading = false;
        }
    }

    function toggleSelect(id: number) {
        const next = new Set(selectedIds);
        if (next.has(id)) {
            next.delete(id);
        } else {
            next.add(id);
        }
        selectedIds = next;
    }

    function selectAllInGroup(items: DiscrepancySchema[]) {
        const next = new Set(selectedIds);
        const allSelected = items.every(i => next.has(i.id));
        if (allSelected) {
            items.forEach(i => next.delete(i.id));
        } else {
            items.forEach(i => next.add(i.id));
        }
        selectedIds = next;
    }

    function selectAllMissing() {
        const ids = missingItems.map(d => d.id);
        const allSelected = ids.every(id => selectedIds.has(id));
        if (allSelected) {
            ids.forEach(id => selectedIds.delete(id));
        } else {
            ids.forEach(id => selectedIds.add(id));
        }
        selectedIds = new Set(selectedIds);
    }

    function selectAllPending() {
        const ids = pendingItems.map(d => d.id);
        const allSelected = ids.every(id => selectedIds.has(id));
        if (allSelected) {
            ids.forEach(id => selectedIds.delete(id));
        } else {
            ids.forEach(id => selectedIds.add(id));
        }
        selectedIds = new Set(selectedIds);
    }

    function clearSelection() {
        selectedIds = new Set();
    }

    const selectedItems = $derived(discrepancies.filter(d => selectedIds.has(d.id)));
    const selectedWithBackups = $derived(selectedItems.filter(d => d.has_versions));
    const selectedWithoutBackups = $derived(selectedItems.filter(d => !d.has_versions));

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

    function formatPath(path: string) {
        const parts = path.split('/');
        if (parts.length <= 3) return path;
        const headParts = parts.slice(0, -2);
        const tailParts = parts.slice(-2);
        return {
            head: headParts.join('/'),
            tail: tailParts.join('/')
        };
    }

    onMount(loadDiscrepancies);

    const missingItems = $derived(discrepancies.filter(d => d.is_deleted));
    const pendingItems = $derived(discrepancies.filter(d => !d.is_deleted));
    const allMissingSelected = $derived(missingItems.length > 0 && missingItems.every(d => selectedIds.has(d.id)));
    const allPendingSelected = $derived(pendingItems.length > 0 && pendingItems.every(d => selectedIds.has(d.id)));
</script>

<svelte:head>
    <title>Discrepancies - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 animate-in fade-in duration-700">
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
        <div class="grid grid-cols-2 gap-3">
            <StatCard label="Missing from disk" value={missingItems.length} subLabel="Files the scanner did not find" variant="error" />
            <StatCard label="Pending confirmation" value={pendingItems.length} subLabel="Tracked files not yet confirmed" variant="warning" />
        </div>

        <!-- Batch Selection Toolbar -->
        {#if selectedIds.size > 0}
            <Card class="p-4 bg-blue-500/10 border-blue-500/30 flex items-center gap-4">
                <span class="text-sm font-medium text-blue-400">
                    {selectedIds.size} file(s) selected
                    {#if selectedWithBackups.length > 0 && selectedWithoutBackups.length > 0}
                        <span class="opacity-60">
                            ({selectedWithBackups.length} backed up, {selectedWithoutBackups.length} no backup)
                        </span>
                    {/if}
                </span>
                <div class="flex-1"></div>
                {#if selectedWithBackups.length > 0}
                    <Button
                        variant="outline"
                        size="sm"
                        class="h-8 text-xs border-success-color/30 text-success-color hover:bg-success-color/10"
                        onclick={() => batchAction = 'recover'}
                    >
                        <HardDriveDownload size={12} class="mr-1.5" /> Add to recovery
                    </Button>
                {/if}
                {#if selectedWithoutBackups.length > 0}
                    <Button
                        variant="outline"
                        size="sm"
                        class="h-8 text-xs border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/10"
                        onclick={() => batchAction = 'acknowledge'}
                    >
                        <ShieldCheck size={12} class="mr-1.5" /> Acknowledge loss
                    </Button>
                {/if}
                <Button
                    variant="ghost"
                    size="sm"
                    class="h-8 text-xs text-text-secondary"
                    onclick={clearSelection}
                >
                    <X size={12} class="mr-1.5" /> Clear
                </Button>
            </Card>
        {/if}

        <!-- Batch Action Confirmation -->
        {#if batchAction}
            <Card class="p-6 bg-bg-secondary border-border-color">
                <div class="flex items-center justify-between">
                    <div>
                        {#if batchAction === 'recover'}
                            <h4 class="text-sm font-bold text-success-color">
                                Add {selectedWithBackups.length} file(s) to recovery queue?
                            </h4>
                            <p class="text-xs text-text-secondary opacity-60 mt-1">
                                These files will be queued for restoration from archive media.
                            </p>
                        {:else}
                            <h4 class="text-sm font-bold text-yellow-400">
                                Acknowledge loss of {selectedWithoutBackups.length} file(s)?
                            </h4>
                            <p class="text-xs text-text-secondary opacity-60 mt-1">
                                These files have no backup on archive media. They will be marked as acknowledged lost.
                            </p>
                        {/if}
                    </div>
                    <div class="flex items-center gap-2">
                        <Button variant="outline" size="sm" onclick={() => batchAction = null}>
                            Cancel
                        </Button>
                        <Button
                            size="sm"
                            class={cn(
                                batchAction === 'recover' && 'bg-success-color hover:bg-success-color/90',
                                batchAction === 'acknowledge' && 'bg-yellow-500 hover:bg-yellow-500/90 text-black'
                            )}
                            onclick={executeBatchAction}
                            disabled={batchLoading}
                        >
                            {#if batchLoading}
                                <RotateCw size={14} class="mr-2 animate-spin" />
                            {/if}
                            {#if batchAction === 'recover'}
                                Add to recovery
                            {:else}
                                Acknowledge loss
                            {/if}
                        </Button>
                    </div>
                </div>
            </Card>
        {/if}

        <div class="space-y-8">
            <!-- MISSING ITEMS SECTION -->
            {#if missingItems.length > 0}
                <section class="space-y-4">
                    <div class="flex items-center gap-3">
                        <SectionHeader title="Missing from disk" icon={FileX} iconColor="text-error-color" class="flex-1" />
                        <button
                            class="text-[10px] font-medium text-text-secondary uppercase tracking-wider hover:text-text-primary transition-colors px-2"
                            onclick={selectAllMissing}
                        >
                            {allMissingSelected ? 'Deselect all' : 'Select all'}
                        </button>
                    </div>

                    <div class="grid grid-cols-1 gap-3">
                        {#each groupedItems.filter(g => g.items.some(i => i.is_deleted)) as group}
                            <div class="space-y-2">
                                <div class="flex items-center gap-2 px-1">
                                    <button
                                        class="flex items-center gap-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
                                        onclick={() => toggleCollapse('missing-' + group.directory)}
                                    >
                                        {#if collapsedDirs['missing-' + group.directory]}
                                            <ChevronRight size={14} />
                                        {:else}
                                            <ChevronDown size={14} />
                                        {/if}
                                        <FolderOpen size={14} />
                                        <span class="mono text-xs">{group.directory}</span>
                                        <span class="text-[10px] font-normal opacity-40">({group.items.filter(i => i.is_deleted).length})</span>
                                    </button>
                                    <button
                                        class="text-[10px] text-text-secondary opacity-40 hover:opacity-70 hover:text-text-primary transition-colors ml-auto"
                                        onclick={() => selectAllInGroup(group.items.filter(i => i.is_deleted))}
                                    >
                                        {group.items.filter(i => i.is_deleted).every(i => selectedIds.has(i.id)) ? 'Deselect group' : 'Select group'}
                                    </button>
                                </div>

                                {#if !collapsedDirs['missing-' + group.directory]}
                                    {#each group.items.filter(i => i.is_deleted) as item (item.id)}
                                        {@const path = formatPath(item.path)}
                                        <Card class="px-5 py-3 bg-bg-secondary/40 border-border-color/40 hover:bg-bg-secondary transition-colors group">
                                            <div class="flex items-center gap-4">
                                                <input
                                                    type="checkbox"
                                                    class="rounded border-border-color/30 bg-transparent cursor-pointer shrink-0"
                                                    checked={selectedIds.has(item.id)}
                                                    onchange={(e) => e.currentTarget.checked ? toggleSelect(item.id) : toggleSelect(item.id)}
                                                />

                                                <StatusBadge variant="error">Missing</StatusBadge>

                                                <div class="flex-1 min-w-0">
                                                    {#if typeof path === 'string'}
                                                        <span class="text-sm font-medium text-text-primary mono truncate block" title={item.path}>
                                                            {path}
                                                        </span>
                                                    {:else}
                                                        <div class="flex flex-col gap-0.5">
                                                            <span class="text-xs font-medium text-text-secondary mono leading-tight" title={item.path}>
                                                                {path.head}
                                                            </span>
                                                            <span class="text-sm font-medium text-text-primary mono leading-tight" title={item.path}>
                                                                {path.tail}
                                                            </span>
                                                        </div>
                                                    {/if}
                                                    <p class="text-xs text-text-secondary mt-0.5 opacity-60">{formatSize(item.size)} · Last seen: {item.last_seen_timestamp ? formatLocalDate(item.last_seen_timestamp) : '—'}</p>
                                                </div>

                                                <div class="flex items-center gap-1.5 shrink-0">
                                                    {#if item.has_versions}
                                                        <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-success-color/10 text-success-color">
                                                            <ShieldCheck size={11} />
                                                            <span class="text-[10px] font-medium">On archive</span>
                                                        </div>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            class="h-8 w-8 text-success-color hover:bg-success-color/10 opacity-40 group-hover:opacity-100 transition-opacity"
                                                            onclick={() => addToRecoveryQueue(item.id)}
                                                            disabled={recovering === item.id}
                                                            title="Add to recovery queue"
                                                        >
                                                            {#if recovering === item.id}
                                                                <RotateCw size={14} class="animate-spin" />
                                                            {:else}
                                                                <HardDriveDownload size={14} />
                                                            {/if}
                                                        </Button>
                                                    {:else}
                                                        <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-yellow-500/10 text-yellow-500">
                                                            <EyeOff size={11} />
                                                            <span class="text-[10px] font-medium">No backup</span>
                                                        </div>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            class="h-8 w-8 text-yellow-500 hover:bg-yellow-500/10 opacity-40 group-hover:opacity-100 transition-opacity"
                                                            onclick={() => acknowledgeLoss(item.id)}
                                                            disabled={acknowledging === item.id}
                                                            title="Acknowledge loss"
                                                        >
                                                            {#if acknowledging === item.id}
                                                                <RotateCw size={14} class="animate-spin" />
                                                            {:else}
                                                                <ShieldCheck size={14} />
                                                            {/if}
                                                        </Button>
                                                    {/if}
                                                </div>
                                            </div>
                                        </Card>
                                    {/each}
                                {/if}
                            </div>
                        {/each}
                    </div>
                </section>
            {/if}

            <!-- PENDING ITEMS SECTION -->
            {#if pendingItems.length > 0}
                <section class="space-y-4">
                    <div class="flex items-center gap-3">
                        <SectionHeader title="Pending confirmation" icon={FileQuestion} iconColor="text-yellow-500" class="flex-1" />
                        <button
                            class="text-[10px] font-medium text-text-secondary uppercase tracking-wider hover:text-text-primary transition-colors px-2"
                            onclick={selectAllPending}
                        >
                            {allPendingSelected ? 'Deselect all' : 'Select all'}
                        </button>
                    </div>

                    <div class="grid grid-cols-1 gap-3">
                        {#each groupedItems.filter(g => g.items.some(i => !i.is_deleted)) as group}
                            <div class="space-y-2">
                                <div class="flex items-center gap-2 px-1">
                                    <button
                                        class="flex items-center gap-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors"
                                        onclick={() => toggleCollapse('pending-' + group.directory)}
                                    >
                                        {#if collapsedDirs['pending-' + group.directory]}
                                            <ChevronRight size={14} />
                                        {:else}
                                            <ChevronDown size={14} />
                                        {/if}
                                        <FolderOpen size={14} />
                                        <span class="mono text-xs">{group.directory}</span>
                                        <span class="text-[10px] font-normal opacity-40">({group.items.filter(i => !i.is_deleted).length})</span>
                                    </button>
                                    <button
                                        class="text-[10px] text-text-secondary opacity-40 hover:opacity-70 hover:text-text-primary transition-colors ml-auto"
                                        onclick={() => selectAllInGroup(group.items.filter(i => !i.is_deleted))}
                                    >
                                        {group.items.filter(i => !i.is_deleted).every(i => selectedIds.has(i.id)) ? 'Deselect group' : 'Select group'}
                                    </button>
                                </div>

                                {#if !collapsedDirs['pending-' + group.directory]}
                                    {#each group.items.filter(i => !i.is_deleted) as item (item.id)}
                                        {@const path = formatPath(item.path)}
                                        <Card class="px-5 py-3 bg-bg-secondary/40 border-border-color/40 hover:bg-bg-secondary transition-colors group">
                                            <div class="flex items-center gap-4">
                                                <input
                                                    type="checkbox"
                                                    class="rounded border-border-color/30 bg-transparent cursor-pointer shrink-0"
                                                    checked={selectedIds.has(item.id)}
                                                    onchange={(e) => e.currentTarget.checked ? toggleSelect(item.id) : toggleSelect(item.id)}
                                                />

                                                <StatusBadge variant="warning">Pending</StatusBadge>

                                                <div class="flex-1 min-w-0">
                                                    {#if typeof path === 'string'}
                                                        <span class="text-sm font-medium text-text-primary mono truncate block" title={item.path}>
                                                            {path}
                                                        </span>
                                                    {:else}
                                                        <div class="flex flex-col gap-0.5">
                                                            <span class="text-xs font-medium text-text-secondary mono leading-tight" title={item.path}>
                                                                {path.head}
                                                            </span>
                                                            <span class="text-sm font-medium text-text-primary mono leading-tight" title={item.path}>
                                                                {path.tail}
                                                            </span>
                                                        </div>
                                                    {/if}
                                                    <p class="text-xs text-text-secondary mt-0.5 opacity-60">{formatSize(item.size)}</p>
                                                </div>

                                                <div class="flex items-center gap-1.5 shrink-0">
                                                    {#if item.has_versions}
                                                        <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-success-color/10 text-success-color">
                                                            <ShieldCheck size={11} />
                                                            <span class="text-[10px] font-medium">On archive</span>
                                                        </div>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            class="h-8 w-8 text-success-color hover:bg-success-color/10 opacity-40 group-hover:opacity-100 transition-opacity"
                                                            onclick={() => addToRecoveryQueue(item.id)}
                                                            disabled={recovering === item.id}
                                                            title="Add to recovery queue"
                                                        >
                                                            {#if recovering === item.id}
                                                                <RotateCw size={14} class="animate-spin" />
                                                            {:else}
                                                                <HardDriveDownload size={14} />
                                                            {/if}
                                                        </Button>
                                                    {:else}
                                                        <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-yellow-500/10 text-yellow-500">
                                                            <EyeOff size={11} />
                                                            <span class="text-[10px] font-medium">No backup</span>
                                                        </div>
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            class="h-8 w-8 text-yellow-500 hover:bg-yellow-500/10 opacity-40 group-hover:opacity-100 transition-opacity"
                                                            onclick={() => acknowledgeLoss(item.id)}
                                                            disabled={acknowledging === item.id}
                                                            title="Acknowledge loss"
                                                        >
                                                            {#if acknowledging === item.id}
                                                                <RotateCw size={14} class="animate-spin" />
                                                            {:else}
                                                                <ShieldCheck size={14} />
                                                            {/if}
                                                        </Button>
                                                    {/if}
                                                </div>
                                            </div>
                                        </Card>
                                    {/each}
                                {/if}
                            </div>
                        {/each}
                    </div>
                </section>
            {/if}
        </div>
    {/if}
</div>
