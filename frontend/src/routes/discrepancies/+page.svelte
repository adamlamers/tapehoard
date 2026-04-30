<script lang="ts">
    import { onMount } from 'svelte';
    import {
        AlertTriangle,
        FileX,
        FileQuestion,
        RotateCw,
        Check,
        Trash2,
        ShieldCheck,
        EyeOff
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import { Card } from '$lib/components/ui/card';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import { cn, formatLocalDate, formatLocalTime } from '$lib/utils';
    import { toast } from 'svelte-sonner';
    import { client } from '$lib/api/client.gen';

    interface Discrepancy {
        id: number;
        path: string;
        size: number;
        mtime: string;
        last_seen_timestamp: string | null;
        sha256_hash: string | null;
        is_deleted: boolean;
        has_versions: boolean;
    }

    let discrepancies = $state<Discrepancy[]>([]);
    let loading = $state(true);
    let confirming = $state<number | null>(null);
    let dismissing = $state<number | null>(null);
    let deleting = $state<number | null>(null);

    async function loadDiscrepancies() {
        loading = true;
        try {
            const response = await client.request<Discrepancy[]>({
                method: 'GET',
                url: '/system/discrepancies'
            });
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

    async function confirmDeleted(id: number) {
        confirming = id;
        try {
            await client.request({
                method: 'POST',
                url: `/system/discrepancies/${id}/confirm`
            });
            toast.success("File marked as confirmed deleted");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to confirm deletion");
        } finally {
            confirming = null;
        }
    }

    async function dismiss(id: number) {
        dismissing = id;
        try {
            await client.request({
                method: 'POST',
                url: `/system/discrepancies/${id}/dismiss`
            });
            toast.success("Discrepancy dismissed");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to dismiss discrepancy");
        } finally {
            dismissing = null;
        }
    }

    async function hardDelete(id: number) {
        deleting = id;
        try {
            await client.request({
                method: 'DELETE',
                url: `/system/discrepancies/${id}`
            });
            toast.success("File record permanently deleted");
            await loadDiscrepancies();
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to delete record");
        } finally {
            deleting = null;
        }
    }

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

    function formatPath(path: string, maxLength = 70) {
        if (path.length <= maxLength) return { head: path, tail: null };
        const parts = path.split('/');
        if (parts.length <= 3) return { head: path, tail: null };

        const headParts = parts.slice(0, -2);
        const tailParts = parts.slice(-2);
        const head = headParts.join('/');
        const tail = tailParts.join('/');

        return { head, tail };
    }

    onMount(loadDiscrepancies);

    const missingItems = $derived(discrepancies.filter(d => d.is_deleted));
    const pendingItems = $derived(discrepancies.filter(d => !d.is_deleted));
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
            <Button variant="outline" onclick={loadDiscrepancies}>
                <RotateCw size={14} class={cn("mr-2", loading && "animate-spin")} /> Refresh
            </Button>
        {/snippet}
    </PageHeader>

    {#if loading && discrepancies.length === 0}
        <div class="space-y-6">
            <div class="h-40 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
            <div class="h-64 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
        </div>
    {:else if discrepancies.length === 0}
        <Card class="p-12 bg-bg-secondary border-border-color shadow-xl flex flex-col items-center justify-center text-center">
            <div class="w-16 h-16 bg-success-color/10 rounded-2xl flex items-center justify-center text-success-color mb-6">
                <ShieldCheck size={32} />
            </div>
            <h3 class="text-xl font-bold text-text-primary mb-2">All clear</h3>
            <p class="text-sm text-text-secondary opacity-60">
                No discrepancies detected. All tracked files are present on disk.
            </p>
        </Card>
    {:else}
        <div class="space-y-6">
            <!-- Summary Cards -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Card class="p-6 bg-bg-secondary border-border-color shadow-xl">
                    <div class="flex items-start gap-4">
                        <div class="w-10 h-10 bg-error-color/10 rounded-xl flex items-center justify-center text-error-color shrink-0">
                            <FileX size={20} />
                        </div>
                        <div class="flex-1">
                            <span class="text-xs text-text-secondary opacity-60 block mb-1">Missing from disk</span>
                            <h4 class="text-2xl font-bold text-error-color mono tabular-nums">{missingItems.length}</h4>
                            <p class="text-[10px] font-medium text-text-secondary uppercase opacity-40 mt-1">Files the scanner did not find</p>
                        </div>
                    </div>
                </Card>

                <Card class="p-6 bg-bg-secondary border-border-color shadow-xl">
                    <div class="flex items-start gap-4">
                        <div class="w-10 h-10 bg-yellow-500/10 rounded-xl flex items-center justify-center text-yellow-500 shrink-0">
                            <FileQuestion size={20} />
                        </div>
                        <div class="flex-1">
                            <span class="text-xs text-text-secondary opacity-60 block mb-1">Pending confirmation</span>
                            <h4 class="text-2xl font-bold text-yellow-500 mono tabular-nums">{pendingItems.length}</h4>
                            <p class="text-[10px] font-medium text-text-secondary uppercase opacity-40 mt-1">Tracked files not yet confirmed</p>
                        </div>
                    </div>
                </Card>
            </div>

            <!-- Discrepancy List -->
            <Card class="bg-bg-secondary border-border-color shadow-xl overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead>
                            <tr class="border-b border-border-color/30">
                                <th class="text-left text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">Status</th>
                                <th class="text-left text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">File path</th>
                                <th class="text-right text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">Size</th>
                                <th class="text-left text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">Last seen</th>
                                <th class="text-center text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">Backed up</th>
                                <th class="text-right text-4xs font-bold uppercase text-text-secondary opacity-40 px-6 py-3 tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each discrepancies as item (item.id)}
                                {@const path = formatPath(item.path)}
                                <tr class="border-b border-border-color/10 hover:bg-white/[0.02] transition-colors group">
                                    <td class="px-6 py-4 align-top">
                                        {#if item.is_deleted}
                                            <StatusBadge variant="error">Missing</StatusBadge>
                                        {:else}
                                            <StatusBadge variant="warning">Pending</StatusBadge>
                                        {/if}
                                    </td>
                                    <td class="px-6 py-4 align-top">
                                        <div class="max-w-[500px]">
                                            {#if path.tail}
                                                <div class="flex flex-col gap-0.5">
                                                    <span class="text-xs font-medium text-text-secondary mono leading-tight" title={item.path}>
                                                        {path.head}
                                                    </span>
                                                    <span class="text-sm font-medium text-text-primary mono leading-tight" title={item.path}>
                                                        {path.tail}
                                                    </span>
                                                </div>
                                            {:else}
                                                <span class="text-sm font-medium text-text-primary mono truncate block" title={item.path}>
                                                    {path.head}
                                                </span>
                                            {/if}
                                        </div>
                                    </td>
                                    <td class="px-6 py-4 text-right align-top">
                                        <span class="text-xs text-text-secondary mono">{formatSize(item.size)}</span>
                                    </td>
                                    <td class="px-6 py-4 align-top">
                                        <span class="text-xs text-text-secondary mono">
                                            {#if item.last_seen_timestamp}
                                                {formatLocalDate(item.last_seen_timestamp)}
                                            {:else}
                                                —
                                            {/if}
                                        </span>
                                    </td>
                                    <td class="px-6 py-4 text-center align-top">
                                        {#if item.has_versions}
                                            <div class="inline-flex items-center gap-1.5 text-success-color">
                                                <ShieldCheck size={14} />
                                                <span class="text-xs font-medium">Yes</span>
                                            </div>
                                        {:else}
                                            <div class="inline-flex items-center gap-1.5 text-text-secondary opacity-40">
                                                <EyeOff size={14} />
                                                <span class="text-xs font-medium">No</span>
                                            </div>
                                        {/if}
                                    </td>
                                    <td class="px-6 py-4 align-top">
                                        <div class="flex items-center justify-end gap-2 pt-1">
                                            {#if item.is_deleted}
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-7 px-2 text-xs text-text-secondary hover:text-success-color"
                                                    onclick={() => dismiss(item.id)}
                                                    disabled={dismissing === item.id || confirming === item.id || deleting === item.id}
                                                >
                                                    {#if dismissing === item.id}
                                                        <RotateCw size={12} class="animate-spin" />
                                                    {:else}
                                                        <Check size={12} />
                                                    {/if}
                                                    <span class="ml-1">Dismiss</span>
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-7 px-2 text-xs text-text-secondary hover:text-error-color"
                                                    onclick={() => hardDelete(item.id)}
                                                    disabled={dismissing === item.id || confirming === item.id || deleting === item.id}
                                                >
                                                    {#if deleting === item.id}
                                                        <RotateCw size={12} class="animate-spin" />
                                                    {:else}
                                                        <Trash2 size={12} />
                                                    {/if}
                                                    <span class="ml-1">Purge</span>
                                                </Button>
                                            {:else}
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-7 px-2 text-xs text-text-secondary hover:text-error-color"
                                                    onclick={() => confirmDeleted(item.id)}
                                                    disabled={dismissing === item.id || confirming === item.id || deleting === item.id}
                                                >
                                                    {#if confirming === item.id}
                                                        <RotateCw size={12} class="animate-spin" />
                                                    {:else}
                                                        <FileX size={12} />
                                                    {/if}
                                                    <span class="ml-1">Confirm</span>
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-7 px-2 text-xs text-text-secondary hover:text-success-color"
                                                    onclick={() => dismiss(item.id)}
                                                    disabled={dismissing === item.id || confirming === item.id || deleting === item.id}
                                                >
                                                    {#if dismissing === item.id}
                                                        <RotateCw size={12} class="animate-spin" />
                                                    {:else}
                                                        <Check size={12} />
                                                    {/if}
                                                    <span class="ml-1">Dismiss</span>
                                                </Button>
                                            {/if}
                                        </div>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </Card>
        </div>
    {/if}
</div>
