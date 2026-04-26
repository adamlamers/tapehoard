<script lang="ts">
    import { onMount } from 'svelte';
    import {
        PieChart,
        TrendingUp,
        ShieldAlert,
        HardDrive,
        FileText,
        Clock,
        RotateCw,
        Info,
        AlertCircle,
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
    import { getFilesystemInsightsInventoryInsightsGet } from '$lib/api';
    import { cn } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let insights = $state<any>(null);
    let loading = $state(true);

    async function loadInsights() {
        loading = true;
        try {
            const response = await getFilesystemInsightsInventoryInsightsGet();
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

    function getDedupeRatio() {
        if (!insights?.summary.unique_bytes) return "1:1";
        const ratio = insights.summary.total_bytes / insights.summary.unique_bytes;
        return `${ratio.toFixed(2)}:1`;
    }

    function mapDirectoryTree(nodes: any[]): any[] {
        if (!nodes) return [];
        return nodes.filter(n => n.size > 0).map(n => ({
            label: n.path,
            value: n.size,
            fullPath: n.fullPath,
            children: mapDirectoryTree(n.children)
        }));
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
            <div class="space-y-8">

            <!-- Executive Summary Row -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50">Total Data Scanned</span>
                    <div class="flex items-center justify-between">
                        <span class="text-2xl font-black text-text-primary mono">{formatSize(insights.summary.total_bytes)}</span>
                        <HardDrive size={20} class="text-blue-500/30" />
                    </div>
                </Card>
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2 border-l-4 border-l-success-color">
                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50">Deduplication Savings</span>
                    <div class="flex items-center justify-between">
                        <span class="text-2xl font-black text-success-color mono">{formatSize(insights.summary.total_bytes - insights.summary.unique_bytes)}</span>
                        <TrendingUp size={20} class="text-success-color/30" />
                    </div>
                </Card>
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50">Efficiency Ratio</span>
                    <div class="flex items-center justify-between">
                        <span class="text-2xl font-black text-text-primary mono">{getDedupeRatio()}</span>
                        <Zap size={20} class="text-yellow-500/30" />
                    </div>
                </Card>
                <Card class="p-6 bg-bg-secondary border-border-color flex flex-col gap-2">
                    <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50">Total Tracked Objects</span>
                    <div class="flex items-center justify-between">
                        <span class="text-2xl font-black text-text-primary mono">{insights.summary.total_files.toLocaleString()}</span>
                        <FileText size={20} class="text-blue-500/30" />
                    </div>
                </Card>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <!-- VULNERABILITY BY ROOT -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl overflow-hidden flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-orange-500/10 rounded-lg text-orange-500"><ShieldAlert size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Backup Coverage</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Archival coverage per source root</p>
                        </div>
                    </div>

                    <div class="space-y-6">
                        {#each insights.roots as root}
                            <div class="space-y-2">
                                <div class="flex justify-between items-end px-1">
                                    <span class="text-[10px] font-black text-text-primary mono truncate max-w-[70%]">{root.root}</span>
                                    <span class="text-[10px] font-bold text-text-secondary uppercase">
                                        {((root.protected / (root.protected + root.vulnerable || 1)) * 100).toFixed(1)}% SECURED
                                    </span>
                                </div>
                                <div class="h-4 w-full bg-bg-primary rounded-full border border-border-color overflow-hidden flex">
                                    <div class="h-full bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)] transition-all duration-1000" style="width: {(root.protected / (root.protected + root.vulnerable || 1)) * 100}%"></div>
                                    <div class="h-full bg-orange-500/30 transition-all duration-1000" style="width: {(root.vulnerable / (root.protected + root.vulnerable || 1)) * 100}%"></div>
                                </div>
                                <div class="flex justify-between px-1">
                                    <span class="text-[9px] font-black uppercase text-text-secondary opacity-40">Secured: {formatSize(root.protected)}</span>
                                    <span class="text-[9px] font-black uppercase text-orange-500/60">Vulnerable: {formatSize(root.vulnerable)}</span>
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
                            <div class="p-4 rounded-xl bg-bg-primary/50 border border-border-color flex items-center justify-between group hover:border-blue-500/30 transition-all">
                                <div class="flex items-center gap-4">
                                    <div class={cn(
                                        "p-2 rounded-lg",
                                        age.bucket.includes('Recent') ? "text-orange-500 bg-orange-500/10" :
                                        age.bucket.includes('Warm') ? "text-yellow-500 bg-yellow-500/10" :
                                        "text-blue-400 bg-blue-500/10"
                                    )}>
                                        {#if age.bucket.includes('Recent')}<Flame size={16} />
                                        {:else if age.bucket.includes('Warm')}<Zap size={16} />
                                        {:else}<Snowflake size={16} />{/if}
                                    </div>
                                    <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">{age.bucket}</span>
                                </div>
                                <div class="text-right">
                                    <span class="text-xs font-black text-text-primary mono">{formatSize(age.size)}</span>
                                    <p class="text-[9px] text-text-secondary uppercase font-bold opacity-40">Total Volume</p>
                                </div>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- EXTENSION BREAKDOWN -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-purple-500/10 rounded-lg text-purple-500"><LayoutGrid size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Space by Extension</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Top storage consumers by file type</p>
                        </div>
                    </div>

                    <div class="flex-1 flex flex-col min-h-0 min-h-[300px]">
                        <Treemap items={insights.extensions.filter((e: any) => e.size > 0).map((ext: any) => ({ label: `.${ext.ext}`, value: ext.size }))} />
                    </div>
                </Card>

                <!-- DIRECTORY BREAKDOWN -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8 lg:col-span-2">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-emerald-500/10 rounded-lg text-emerald-500"><FolderTree size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Space by Directory</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Top storage consumers by physical path</p>
                        </div>
                    </div>

                    <div class="flex-1 flex flex-col min-h-0 min-h-[400px]">
                        <Treemap items={mapDirectoryTree(insights.directories)} />
                    </div>
                </Card>

                <!-- REDUNDANCY STATUS -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-success-color/10 rounded-lg text-success-color"><CheckCircle2 size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Media Redundancy</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Physical copy distribution across media</p>
                        </div>
                    </div>

                    <div class="space-y-4">
                        {#each insights.redundancy as red}
                            <div class={cn(
                                "p-4 rounded-xl border flex items-center justify-between",
                                red.copies === 0 ? "bg-error-color/5 border-error-color/20" :
                                red.copies === 1 ? "bg-orange-500/5 border-orange-500/20" :
                                "bg-success-color/5 border-success-color/20"
                            )}>
                                <div class="flex flex-col gap-1">
                                    <span class="text-[11px] font-black uppercase tracking-widest text-text-primary">
                                        {red.copies} Physical {red.copies === 1 ? 'Copy' : 'Copies'}
                                    </span>
                                    <span class="text-[9px] font-bold text-text-secondary uppercase opacity-60">
                                        {red.file_count.toLocaleString()} Tracked Objects
                                    </span>                                </div>
                                <div class="text-right">
                                    <span class={cn(
                                        "text-xs font-black mono",
                                        red.copies === 0 ? "text-error-color" : "text-text-primary"
                                    )}>{formatSize(red.size)}</span>
                                    <p class="text-[9px] text-text-secondary uppercase font-bold opacity-40">Total Volume</p>
                                </div>
                            </div>
                        {/each}
                    </div>
                </Card>

                <!-- TOP DUPLICATES -->
                <Card class="p-8 bg-bg-secondary border-border-color shadow-xl flex flex-col gap-8">
                    <div class="flex items-center gap-3">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500"><TrendingUp size={20} /></div>
                        <div>
                            <h3 class="text-sm font-black uppercase tracking-tight text-text-primary">Redundant Bitstreams</h3>
                            <p class="text-[10px] text-text-secondary font-bold uppercase tracking-widest opacity-50">Top files by deduplication savings</p>
                        </div>
                    </div>

                    <div class="space-y-3">
                        {#each insights.duplicates as dup}
                            <div class="p-4 rounded-xl bg-bg-primary/40 border border-border-color/60 flex items-center justify-between group hover:border-blue-500/30 transition-all">
                                <div class="flex-1 min-w-0 pr-4">
                                    <span class="text-[10px] font-black text-text-primary mono truncate block">{dup.path.split('/').pop()}</span>
                                    <span class="text-[9px] text-text-secondary uppercase font-bold opacity-60 block mt-1">
                                        {dup.copies} Identical Copies Found
                                    </span>
                                </div>
                                <div class="text-right shrink-0 border-l border-border-color/30 pl-4">
                                    <span class="text-[11px] font-black text-success-color mono">-{formatSize(dup.saved)}</span>
                                    <p class="text-[8px] text-text-secondary uppercase font-black tracking-tighter opacity-40">RECLAIMED</p>
                                </div>
                            </div>
                        {:else}
                            <div class="py-12 text-center opacity-20">
                                <TrendingUp size={32} class="mx-auto mb-2" />
                                <p class="text-[10px] font-black uppercase tracking-widest">No major duplicates identified</p>
                            </div>
                        {/each}
                    </div>
                </Card>
            </div>
        </div>
    {/if}
</div>
