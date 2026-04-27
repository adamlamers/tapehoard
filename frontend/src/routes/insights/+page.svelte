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
    import Treemap from '$lib/components/Treemap.svelte';
    import { getSystemAnalyticsInventoryInsightsGet } from '$lib/api';
    import { cn } from '$lib/utils';
    import { toast } from 'svelte-sonner';
    import { goto } from '$app/navigation';

    let insights = $state<any>(null);
    let loading = $state(true);

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

    function formatSize(bytes: number) {
        if (!bytes) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
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

<div class="flex flex-col gap-8 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <PieChart class="text-blue-500" size={28} />
                Insights
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                System Analytics & Statistics
            </p>
        </div>

        <Button variant="outline" size="icon" class="h-10 w-10 border-border-color z-10" onclick={loadInsights} disabled={loading}>
            <RotateCw size={18} class={loading ? 'animate-spin' : ''} />
        </Button>
    </header>

    {#if loading}
        <div class="flex-1 flex flex-col items-center justify-center gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-blue-500" />
            <span class="text-xs font-black uppercase tracking-widest text-text-secondary">Loading data...</span>
        </div>
    {:else if insights}
        <div class="flex flex-col gap-8 pb-12">
            <!-- Global Metrics -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-60">Total Tracked</span>
                    <span class="text-2xl font-black text-text-primary tabular-nums">{formatSize(insights.summary.total_bytes)}</span>
                </Card>
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-60">Replication Status</span>
                    <span class="text-2xl font-black text-success-color tabular-nums">{((insights.summary.protected_bytes / (insights.summary.total_bytes || 1)) * 100).toFixed(1)}%</span>
                </Card>
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary opacity-60">Vulnerable Data</span>
                    <span class="text-2xl font-black text-error-color tabular-nums">{formatSize(insights.summary.vulnerable_bytes)}</span>
                </Card>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <!-- ROOT SOURCE HEALTH -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500"><LayoutGrid size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Source Protection Status</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Archive coverage per defined source root</p>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {#each insights.roots as root}
                            <div class="space-y-3 p-4 rounded-xl bg-bg-primary/50 border border-border-color">
                                <div class="flex justify-between items-end px-1">
                                    <span class="text-[10px] font-black text-text-primary mono truncate max-w-[70%]">{root.root}</span>
                                    <span class="text-[10px] font-bold text-text-secondary uppercase">
                                        {((root.protected / (root.protected + root.vulnerable || 1)) * 100).toFixed(1)}%
                                    </span>
                                </div>
                                <div class="h-4 w-full bg-bg-primary rounded-full border border-border-color overflow-hidden flex">
                                    <div class="h-full bg-blue-500" style="width: {(root.protected / (root.protected + root.vulnerable || 1)) * 100}%"></div>
                                    <div class="h-full bg-text-secondary/10" style="width: {(root.vulnerable / (root.protected + root.vulnerable || 1)) * 100}%"></div>
                                </div>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- DATA AGING HEATMAP -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500"><Clock size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">File Age</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Data distribution by modified age</p>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 gap-4">
                        {#each insights.aging as age}
                            <div class="p-4 rounded-xl bg-bg-primary/50 border border-border-color flex items-center justify-between group">
                                <div class="flex items-center gap-4">
                                    <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">{age.bucket}</span>
                                </div>
                                <div class="text-right">
                                    <span class="text-xs font-black text-text-primary mono">{formatSize(age.size)}</span>
                                </div>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- REDUNDANCY STATUS -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-success-color/10 rounded-lg text-success-color"><CheckCircle2 size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Media Redundancy</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Physical copy distribution</p>
                        </div>
                    </div>

                    <div class="space-y-4">
                        {#each insights.redundancy as red}
                            <div class="p-4 rounded-xl border flex items-center justify-between bg-bg-primary/50 border-border-color">
                                <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">{red.copies} Copies</span>
                                <span class="text-xs font-black text-text-primary mono">{formatSize(red.size)}</span>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- EXTENSION BREAKDOWN (Full Width) -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-purple-500/10 rounded-lg text-purple-500"><LayoutGrid size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Space by Extension</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Top storage consumers by file type</p>
                        </div>
                    </div>

                    <div class="flex-1 flex flex-col min-h-0 min-h-[400px]">
                        <Treemap items={insights.extensions.filter((e: any) => e.size > 0).map((ext: any) => ({ label: `.${ext.ext}`, value: ext.size }))} />
                    </div>
                </Card>

                <!-- DIRECTORY BREAKDOWN (Full Width) -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-emerald-500/10 rounded-lg text-emerald-500"><FolderTree size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Space by Directory</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Top storage consumers by physical path</p>
                        </div>
                    </div>

                    <div class="flex-1 flex flex-col min-h-0 min-h-[500px]">
                        <Treemap
                            items={mapDirectoryTree(insights.directories)}
                            onSelect={handleDirectorySelect}
                        />
                    </div>
                </Card>
            </div>
        </div>
    {/if}
</div>
