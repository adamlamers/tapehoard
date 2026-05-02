<script lang="ts">
    import { onMount } from 'svelte';
    import {
        PieChart,
        RotateCw,
        Clock,
        CheckCircle2,
        Zap,
        Snowflake,
        Flame,
        LayoutGrid,
        FolderTree
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import StatCard from '$lib/components/ui/StatCard.svelte';
    import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
    import Treemap from '$lib/components/Treemap.svelte';
    import { getSystemAnalyticsInventoryInsightsGet, getDirectoryTreemapInventoryDirectoriesGet } from '$lib/api';
    import { cn, formatSize } from '$lib/utils';
    import { toast } from 'svelte-sonner';
    import { goto } from '$app/navigation';

    let insights = $state<any>(null);
    let loading = $state(true);
    let dirTreemapLoaded = $state(false);
    let dirTreemapLoading = $state(false);
    let dirTreemapData = $state<any[]>([]);

    async function loadInsights() {
        loading = true;
        try {
            const response = await getSystemAnalyticsInventoryInsightsGet();
            if (response.data) insights = response.data;
        } catch (error) {
            toast.error("Failed to generate analytics");
        } finally {
            loading = false;
        }
    }

    async function loadDirTreemap() {
        if (dirTreemapLoaded) return;
        dirTreemapLoading = true;
        try {
            const response = await getDirectoryTreemapInventoryDirectoriesGet();
            if (response.data) {
                dirTreemapData = mapDirectoryTree(response.data as any[]);
                dirTreemapLoaded = true;
            }
        } catch (error) {
            toast.error("Failed to load directory treemap");
        } finally {
            dirTreemapLoading = false;
        }
    }

    function mapDirectoryTree(nodes: any[]): any[] {
        if (!nodes) return [];
        return nodes.filter((n: any) => n.size > 0).map((n: any) => ({
            label: n.path,
            value: n.size,
            fullPath: n.fullPath || n.path, // fallback to path if fullPath is missing
            children: mapDirectoryTree(n.children)
        }));
    }

    function handleDirectorySelect(path: string) {
        // Navigate to Live Filesystem and pre-select the path
        goto(`/filesystem?path=${encodeURIComponent(path)}`);
    }

    onMount(loadInsights);
</script>

<svelte:head>
    <title>Operational Intelligence - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-6 animate-in fade-in duration-700">
    <PageHeader
        title="Insights"
        description="System analytics & statistics"
        icon={PieChart}
    >
        {#snippet actions()}
            <Button variant="outline" size="icon" onclick={loadInsights} disabled={loading}>
                <RotateCw size={16} class={loading ? 'animate-spin' : ''} />
            </Button>
        {/snippet}
    </PageHeader>

    {#if loading}
        <div class="flex-1 flex flex-col items-center justify-center gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-blue-500" />
            <span class="text-xs font-black uppercase tracking-widest text-text-secondary">Loading data...</span>
        </div>
    {:else if insights}
        <div class="flex flex-col gap-6 pb-12">
            <!-- Global Metrics -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <StatCard label="Total tracked" value={formatSize(insights.summary.total_bytes)} />
                <StatCard label="Replication status" value={((insights.summary.protected_bytes / (insights.summary.total_bytes || 1)) * 100).toFixed(1) + "%"} variant="success" />
                <StatCard label="Vulnerable data" value={formatSize(insights.summary.vulnerable_bytes)} variant="error" />
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- ROOT SOURCE HEALTH -->
                <Card class="p-5 shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <SectionHeader title="Source protection status" icon={LayoutGrid} iconColor="text-blue-500" />

                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {#each insights.roots as root}
                            <div class="space-y-3 p-4 rounded-xl bg-bg-primary/50 border border-border-color">
                                <div class="flex justify-between items-end px-1">
                                    <span class="text-xs font-medium text-text-primary mono truncate max-w-[70%]">{root.root}</span>
                                    <span class="text-xs font-medium text-text-secondary">
                                        {((root.protected / (root.protected + root.vulnerable || 1)) * 100).toFixed(1)}%
                                    </span>
                                </div>
                                <ProgressBar value={root.protected} max={root.protected + root.vulnerable} size="md" />
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- DATA AGING HEATMAP -->
                <Card class="p-5 shadow-xl flex flex-col gap-8">
                    <SectionHeader title="File age" icon={Clock} iconColor="text-blue-500" />

                    <div class="grid grid-cols-1 gap-4">
                        {#each insights.aging as age}
                            <div class="p-4 rounded-xl bg-bg-primary/50 border border-border-color flex items-center justify-between group">
                                <div class="flex items-center gap-4">
                                    <span class="text-sm font-medium text-text-primary">{age.bucket}</span>
                                </div>
                                <div class="text-right">
                                    <span class="text-xs font-medium text-text-primary mono">{formatSize(age.size)}</span>
                                </div>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- REDUNDANCY STATUS -->
                <Card class="p-5 shadow-xl flex flex-col gap-8">
                    <SectionHeader title="Media redundancy" icon={CheckCircle2} iconColor="text-success-color" />

                    <div class="space-y-4">
                        {#each insights.redundancy as red}
                            <div class="p-4 rounded-xl border flex items-center justify-between bg-bg-primary/50 border-border-color">
                                <span class="text-sm font-medium text-text-primary">{red.copies} copies</span>
                                <span class="text-xs font-medium text-text-primary mono">{formatSize(red.size)}</span>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- EXTENSION BREAKDOWN (Full Width) -->
                <Card class="p-5 shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <SectionHeader title="Space by extension" icon={LayoutGrid} iconColor="text-purple-500" />

                    <div class="flex-1 flex flex-col min-h-0 min-h-[400px]">
                        <Treemap items={insights.extensions.filter((e: any) => e.size > 0).map((ext: any) => ({ label: `.${ext.ext}`, value: ext.size }))} />
                    </div>
                </Card>

                <!-- DIRECTORY BREAKDOWN (Full Width) -->
                <Card class="p-5 shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <div class="flex items-center justify-between">
                        <SectionHeader title="Space by directory" icon={FolderTree} iconColor="text-emerald-500" />
                        {#if !dirTreemapLoaded}
                            <Button variant="outline" size="sm" onclick={loadDirTreemap} disabled={dirTreemapLoading}>
                                {dirTreemapLoading ? 'Loading...' : 'Load directory treemap'}
                            </Button>
                        {/if}
                    </div>

                    {#if dirTreemapLoaded}
                        <div class="flex-1 flex flex-col min-h-0 min-h-[500px]">
                            <Treemap
                                items={dirTreemapData}
                                onSelect={handleDirectorySelect}
                            />
                        </div>
                    {:else}
                        <div class="flex-1 flex items-center justify-center min-h-[300px] border-2 border-dashed border-border-color rounded-xl">
                            <Button variant="outline" onclick={loadDirTreemap} disabled={dirTreemapLoading}>
                                {dirTreemapLoading ? 'Loading...' : 'Click to load directory treemap'}
                            </Button>
                        </div>
                    {/if}
                </Card>
            </div>
        </div>
    {/if}
</div>
