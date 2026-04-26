<script lang="ts">
    import { onMount } from 'svelte';
    import {
        ShieldCheck,
        ShieldAlert,
        FileText,
        Database,
        Clock,
        RotateCw,
        Activity,
        HardDrive,
        Cloud,
        ArrowRight,
        EyeOff,
        FolderTree,
        CassetteTape,
        LayoutDashboard
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import { getDashboardStatsSystemDashboardStatsGet, triggerScanSystemScanPost, triggerIndexingSystemIndexHashPost, type DashboardStatsSchema } from '$lib/api';
    import { cn, formatLocalDate, formatLocalTime } from '$lib/utils';
    import { toast } from 'svelte-sonner';
    import { Zap } from 'lucide-svelte';

    let stats = $state<DashboardStatsSchema | null>(null);
    let loading = $state(true);
    let scanning = $state(false);
    let indexing = $state(false);

    async function loadStats() {
        loading = true;
        try {
            const response = await getDashboardStatsSystemDashboardStatsGet();
            if (response.data) {
                stats = response.data;
            }
        } catch (error) {
            console.error("Failed to load dashboard stats:", error);
        } finally {
            loading = false;
        }
    }

    async function startIndexing() {
        indexing = true;
        try {
            await triggerIndexingSystemIndexHashPost();
            toast.success("Background indexing job initiated");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start indexing");
        } finally {
            indexing = false;
        }
    }

    async function startScan() {
        scanning = true;
        try {
            await triggerScanSystemScanPost();
            toast.success("Scan job initiated successfully");
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to start scan");
        } finally {
            scanning = false;
        }
    }

    onMount(loadStats);

    function formatSize(bytes: number) {
        if (bytes === 0) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }

    const protectionPercent = $derived.by(() => {
        if (!stats || stats.total_files_indexed === 0) return 0;
        const eligible_count = stats.total_files_indexed - stats.ignored_files_count;
        if (eligible_count <= 0) return 0;
        const protected_count = eligible_count - stats.unprotected_files_count;
        return Math.round((protected_count / eligible_count) * 100);
    });

    const dataProtectionPercent = $derived.by(() => {
        if (!stats || stats.total_data_size === 0) return 0;
        const eligible_size = stats.total_data_size - stats.ignored_data_size;
        if (eligible_size <= 0) return 0;
        const protected_size = eligible_size - stats.unprotected_data_size;
        return Math.round((protected_size / eligible_size) * 100);
    });
</script>

<svelte:head>
    <title>Overview - TapeHoard</title>
</svelte:head>

<div class="flex flex-col gap-8 animate-in fade-in duration-700">
    <!-- Header -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <LayoutDashboard class="text-blue-500" size={28} />
                Overview
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                System Status & Statistics
            </p>
        </div>

        <div class="flex gap-3 z-10">
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-border-color" onclick={loadStats}>
                <RotateCw size={14} class={cn("mr-2", loading && "animate-spin")} /> Refresh
            </Button>
            <Button variant="outline" class="h-10 px-6 font-black uppercase tracking-widest text-[10px] border-action-color/30 text-action-color hover:bg-action-color/5" onclick={startIndexing} disabled={indexing}>
                {#if indexing}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Zap size={14} class="mr-2" /> Index Data
                {/if}
            </Button>
            <Button variant="default" class="h-10 px-6 font-black uppercase tracking-widest text-[10px]" onclick={startScan} disabled={scanning}>
                {#if scanning}
                    <RotateCw size={14} class="mr-2 animate-spin" /> Starting...
                {:else}
                    <Activity size={14} class="mr-2" /> Start Full Scan
                {/if}
            </Button>
        </div>
    </header>

    <div class="space-y-8">
        {#if loading && !stats}
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {#each Array(4) as _}
                    <div class="h-32 bg-bg-secondary animate-pulse rounded-xl border border-border-color/50"></div>
                {/each}
            </div>
        {:else if stats}
            {#if stats.total_files_indexed === 0 && stats.media_distribution.LTO === 0 && stats.media_distribution.HDD === 0}
                <!-- ONBOARDING SECTION -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-8 py-4">
                    <Card class="p-8 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-dashed border-2 border-border-color flex flex-col items-center text-center gap-6 group hover:border-blue-500/50 transition-all">
                        <div class="p-4 bg-blue-500/10 rounded-full text-blue-500 group-hover:scale-110 transition-transform">
                            <FolderTree size={40} />
                        </div>
                        <div>
                            <h3 class="text-lg font-black uppercase tracking-tight text-text-primary">1. Define Policy</h3>
                            <p class="text-xs text-text-secondary mt-2 leading-relaxed">Tell TapeHoard which directories to track and what patterns to ignore.</p>
                        </div>
                        <Button variant="outline" class="w-full mt-auto h-11 font-black uppercase tracking-widest text-[10px] border-blue-500/30 text-blue-400 hover:bg-blue-500/10" href="/tracking">
                            Configure Tracking <ArrowRight size={14} class="ml-2" />
                        </Button>
                    </Card>

                    <Card class="p-8 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-dashed border-2 border-border-color flex flex-col items-center text-center gap-6 group hover:border-action-color/50 transition-all">
                        <div class="p-4 bg-action-color/10 rounded-full text-action-color group-hover:scale-110 transition-transform">
                            <Activity size={40} />
                        </div>
                        <div>
                            <h3 class="text-lg font-black uppercase tracking-tight text-text-primary">2. Scan Sources</h3>
                            <p class="text-xs text-text-secondary mt-2 leading-relaxed">Run a system-wide scan to index your files and calculate protection hashes.</p>
                        </div>
                        <Button variant="default" class="w-full mt-auto h-11 font-black uppercase tracking-widest text-[10px]" onclick={startScan}>
                            Start Discovery <ArrowRight size={14} class="ml-2" />
                        </Button>
                    </Card>

                    <Card class="p-8 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-dashed border-2 border-border-color flex flex-col items-center text-center gap-6 group hover:border-success-color/50 transition-all">
                        <div class="p-4 bg-success-color/10 rounded-full text-success-color group-hover:scale-110 transition-transform">
                            <CassetteTape size={40} />
                        </div>
                        <div>
                            <h3 class="text-lg font-black uppercase tracking-tight text-text-primary">3. Add Media</h3>
                            <p class="text-xs text-text-secondary mt-2 leading-relaxed">Register your LTO tapes or backup disks to create a destination for your data.</p>
                        </div>
                        <Button variant="outline" class="w-full mt-auto h-11 font-black uppercase tracking-widest text-[10px] border-success-color/30 text-success-color hover:bg-success-color/10" href="/inventory">
                            Manage Media <ArrowRight size={14} class="ml-2" />
                        </Button>
                    </Card>
                </div>
            {/if}

            <!-- TOP STATS -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <Card class="p-6 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color hover:border-blue-500/30 transition-all group relative overflow-hidden">
                    <div class="absolute inset-0 bg-blue-500/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    <div class="flex items-center gap-4 relative z-10">
                        <div class="p-3 bg-blue-500/10 rounded-lg text-blue-500 border border-blue-500/20 shadow-inner">
                            <FileText size={24} />
                        </div>
                        <div>
                            <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Total Files</span>
                            <span class="text-2xl font-black text-text-primary mono tracking-tight">{stats.total_files_indexed.toLocaleString()}</span>
                        </div>
                    </div>
                </Card>

                <Card class="p-6 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color hover:border-action-color/30 transition-all group relative overflow-hidden">
                    <div class="absolute inset-0 bg-action-color/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    <div class="flex items-center gap-4 relative z-10">
                        <div class="p-3 bg-action-color/10 rounded-lg text-action-color border border-action-color/20 shadow-inner">
                            <Database size={24} />
                        </div>
                        <div>
                            <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Data Volume</span>
                            <span class="text-2xl font-black text-text-primary mono tracking-tight">{formatSize(stats.total_data_size)}</span>
                        </div>
                    </div>
                </Card>

                <Card class="p-6 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color hover:border-success-color/30 transition-all group relative overflow-hidden">
                    <div class="absolute inset-0 bg-success-color/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    <div class="flex items-center gap-4 relative z-10">
                        <div class="p-3 bg-success-color/10 rounded-lg text-success-color border border-success-color/20 shadow-inner">
                            <ShieldCheck size={24} />
                        </div>
                        <div>
                            <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Redundancy Ratio</span>
                            <span class="text-2xl font-black text-text-primary mono tracking-tight">{stats.redundancy_ratio}x</span>
                        </div>
                    </div>
                </Card>

                <Card class="p-6 bg-gradient-to-br from-bg-secondary to-bg-tertiary border-border-color hover:border-orange-500/30 transition-all group relative overflow-hidden">
                    <div class="absolute inset-0 bg-orange-500/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    <div class="flex items-center gap-4 relative z-10">
                        <div class="p-3 bg-orange-500/10 rounded-lg text-orange-500 border border-orange-500/20 shadow-inner">
                            <Clock size={24} />
                        </div>
                        <div>
                            <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block">Last Scan</span>
                            <span class="text-xl font-black text-text-primary tracking-tight">
                                {#if stats.last_scan_time}
                                    {formatLocalTime(stats.last_scan_time)}
                                    <span class="text-[9px] block text-text-secondary opacity-50 uppercase font-black tracking-widest">
                                        {formatLocalDate(stats.last_scan_time)}
                                    </span>
                                {:else}
                                    Never
                                {/if}
                            </span>
                        </div>
                    </div>
                </Card>
            </div>

            <!-- MAIN GRID -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <!-- Protection Health -->
                <Card class="lg:col-span-2 p-8 bg-bg-secondary border-border-color shadow-xl overflow-hidden relative">
                    <div class="absolute top-0 right-0 p-8 opacity-5">
                        <ShieldCheck size={200} />
                    </div>

                    <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-8 flex items-center gap-2">
                        <Activity size={18} class="text-blue-500" />
                        Protection Health Score
                    </h3>

                    <div class="space-y-12 relative z-10">
                        <div class="space-y-4">
                            <div class="flex justify-between items-end">
                                <div>
                                    <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary">Tracking Coverage</span>
                                    <h4 class="text-3xl font-black text-text-primary">{protectionPercent}%</h4>
                                </div>
                                <span class="text-xs font-bold mono text-text-secondary">
                                    {stats.total_files_indexed - stats.ignored_files_count - stats.unprotected_files_count} / {stats.total_files_indexed - stats.ignored_files_count} TRACKED FILES
                                </span>
                            </div>
                            <div class="w-full bg-bg-primary h-4 rounded-full border border-border-color shadow-inner overflow-hidden">
                                <div class="bg-gradient-to-r from-blue-600 to-blue-400 h-full transition-all duration-1000 shadow-[0_0_15px_rgba(59,130,246,0.3)]" style="width: {protectionPercent}%"></div>
                            </div>
                        </div>

                        <div class="space-y-4">
                            <div class="flex justify-between items-end">
                                <div>
                                    <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary">Archive Redundancy</span>
                                    <h4 class="text-3xl font-black text-text-primary">{dataProtectionPercent}%</h4>
                                </div>
                                <span class="text-xs font-bold mono text-text-secondary">
                                    {formatSize(stats.total_data_size - stats.ignored_data_size - stats.unprotected_data_size)} / {formatSize(stats.total_data_size - stats.ignored_data_size)}
                                </span>
                            </div>
                            <div class="w-full bg-bg-primary h-4 rounded-full border border-border-color shadow-inner overflow-hidden">
                                <div class="bg-gradient-to-r from-success-color to-emerald-400 h-full transition-all duration-1000 shadow-[0_0_15px_rgba(46,204,113,0.3)]" style="width: {dataProtectionPercent}%"></div>
                            </div>
                        </div>
                    </div>

                    <div class="mt-12 grid grid-cols-1 md:grid-cols-3 gap-6 p-6 bg-bg-tertiary/50 rounded-xl border border-border-color">
                        <div class="flex gap-4">
                            <div class="p-2 bg-error-color/10 rounded-lg text-error-color h-fit shrink-0">
                                <ShieldAlert size={18} />
                            </div>
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block mb-1">Vulnerable</span>
                                <span class="text-lg font-black text-error-color mono">{stats.unprotected_files_count.toLocaleString()}</span>
                                <p class="text-[9px] font-bold text-text-secondary uppercase tracking-tight mt-1">Files pending archival</p>
                            </div>
                        </div>
                        <div class="flex gap-4 border-l border-border-color/30 pl-4">
                            <div class="p-2 bg-text-secondary/10 rounded-lg text-text-secondary h-fit shrink-0">
                                <EyeOff size={18} />
                            </div>
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block mb-1">Ignored</span>
                                <span class="text-lg font-black text-text-secondary mono">{stats.ignored_files_count.toLocaleString()}</span>
                                <p class="text-[9px] font-bold text-text-secondary uppercase tracking-tight mt-1">Bypassed by policy</p>
                            </div>
                        </div>
                        <div class="flex gap-4 border-l border-border-color/30 pl-4">
                            <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500 h-fit shrink-0">
                                <Database size={18} />
                            </div>
                            <div>
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary block mb-1">Ignored Vol</span>
                                <span class="text-lg font-black text-blue-400 mono">{formatSize(stats.ignored_data_size)}</span>
                                <p class="text-[9px] font-bold text-text-secondary uppercase tracking-tight mt-1">Filtered from index</p>
                            </div>
                        </div>
                    </div>
                </Card>

                <!-- Quick Actions & Media -->
                <div class="space-y-8">
                    <Card class="p-8 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-6">Quick Actions</h3>
                        <div class="space-y-3">
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-blue-500/50 hover:bg-blue-500/5 group" href="/tracking">
                                Review Tracking Rules <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-success-color/50 hover:bg-success-color/5 group" href="/index-browser">
                                Browse Indexed Files <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                            <Button variant="outline" class="w-full justify-between h-12 font-black uppercase tracking-widest text-[10px] border-border-color hover:border-action-color/50 hover:bg-action-color/5 group" href="/inventory">
                                Register New Media <ArrowRight size={14} class="group-hover:translate-x-1 transition-transform" />
                            </Button>
                        </div>
                    </Card>

                    <Card class="p-8 bg-bg-secondary border-border-color shadow-xl h-fit">
                        <h3 class="text-lg font-black uppercase tracking-tighter text-text-primary mb-6">Media distribution</h3>
                        <div class="space-y-6">
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-blue-500/10 rounded-lg flex items-center justify-center text-blue-500">
                                    <CassetteTape size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">LTO Tapes</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.LTO || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-blue-500 h-full" style="width: {stats.media_distribution.LTO > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-yellow-500/10 rounded-lg flex items-center justify-center text-yellow-500">
                                    <HardDrive size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">HDD Storage</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.HDD || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-yellow-500 h-full" style="width: {stats.media_distribution.HDD > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-4">
                                <div class="w-10 h-10 bg-green-500/10 rounded-lg flex items-center justify-center text-green-500">
                                    <Cloud size={20} />
                                </div>
                                <div class="flex-1">
                                    <div class="flex justify-between mb-1">
                                        <span class="text-[10px] font-black uppercase tracking-widest text-text-primary">Cloud Vaults</span>
                                        <span class="text-[10px] font-bold mono">{stats.media_distribution.Cloud || 0} Items</span>
                                    </div>
                                    <div class="w-full bg-bg-primary h-1.5 rounded-full overflow-hidden">
                                        <div class="bg-green-500 h-full" style="width: {stats.media_distribution.Cloud > 0 ? 100 : 0}%"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </Card>
                </div>
            </div>
        {/if}
    </div>
</div>
