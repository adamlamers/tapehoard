<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import {
        Activity,
        Clock,
        RotateCw,
        Search,
        ExternalLink,
        Play,
        StopCircle,
        History,
        ChevronDown,
        RotateCcw,
        ArrowUpRight,
        Filter
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import { POLL_SLOW } from '$lib/config';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
    import EmptyState from '$lib/components/ui/EmptyState.svelte';
    import JobDetailModal from '$lib/components/JobDetailModal.svelte';
    import {
        listJobs,
        getJobCount,
        getJobStats,
        cancelJob as cancelJobApi,
        retryJob as retryJobApi,
        type AppApiCommonJobSchema
    } from '$lib/api';
    import { cn, formatLocalTime, parseUTCDate } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let jobs = $state<AppApiCommonJobSchema[]>([]);
    let totalJobs = $state(0);
    let loading = $state(true);
    let loadingMore = $state(false);
    let pollInterval: any;
    let offset = $state(0);
    let selectedJobId = $state<number | null>(null);

    // Filters
    let typeFilter = $state<string>('ALL');
    let statusFilter = $state<string>('ALL');
    let searchQuery = $state('');

    // Stats
    let stats = $state<{
        total: number;
        completed: number;
        failed: number;
        running: number;
        pending: number;
        success_rate: number;
        avg_duration_seconds: number;
        job_type_counts: Record<string, number>;
    } | null>(null);
    let statsLoading = $state(true);

    const LIMIT = 20;

    async function loadStats() {
        statsLoading = true;
        try {
            const res = await getJobStats();
            if (res.data) stats = res.data as typeof stats;
        } catch (error) {
            console.error("Failed to load stats:", error);
        } finally {
            statsLoading = false;
        }
    }

    async function loadInitialJobs() {
        loading = true;
        try {
            const [jobsRes, countRes] = await Promise.all([
                listJobs({ query: { limit: LIMIT, offset: 0 } }),
                getJobCount()
            ]);

            if (jobsRes.data) jobs = jobsRes.data;
            if (countRes.data) totalJobs = (countRes.data as any).count;
            offset = 0;
        } catch (error) {
            console.error("Failed to load jobs:", error);
        } finally {
            loading = false;
        }
    }

    async function loadMore() {
        if (loadingMore || jobs.length >= totalJobs) return;
        loadingMore = true;
        const newOffset = offset + LIMIT;
        try {
            const response = await listJobs({
                query: { limit: LIMIT, offset: newOffset }
            });
            if (response.data) {
                jobs = [...jobs, ...response.data];
                offset = newOffset;
            }
        } catch (error) {
            toast.error("Failed to load more jobs");
        } finally {
            loadingMore = false;
        }
    }

    async function pollActiveJobs() {
        try {
            const response = await listJobs({
                query: { limit: LIMIT, offset: 0 }
            });
            if (response.data) {
                const updated = response.data;
                const rest = jobs.slice(LIMIT);
                jobs = [...updated, ...rest];
            }

            const countRes = await getJobCount();
            if (countRes.data) totalJobs = (countRes.data as any).count;
        } catch (error) {
            // Silently fail polling
        }
    }

    async function cancelJob(jobId: number) {
        try {
            await cancelJobApi({
                path: { job_id: jobId },
                throwOnError: true
            });
            toast.info(`Cancellation requested for Job #${jobId}`);
            pollActiveJobs();
        } catch (error) {
            toast.error("Failed to cancel job");
        }
    }

    async function retryJob(jobId: number) {
        try {
            const res = await retryJobApi({
                path: { job_id: jobId },
                throwOnError: true
            });
            if (res.data) {
                toast.success(`Retrying as Job #${(res.data as any).new_job_id}`);
                loadInitialJobs();
                loadStats();
            }
        } catch (error: any) {
            toast.error(error.body?.detail || "Failed to retry job");
        }
    }

    function openJobDetail(jobId: number) {
        selectedJobId = jobId;
    }

    function formatDuration(start?: string | null, end?: string | null) {
        const startDate = parseUTCDate(start);
        if (!startDate) return '--';

        const endDate = (end ? parseUTCDate(end) : new Date()) || new Date();
        const seconds = Math.max(0, Math.floor((endDate.getTime() - startDate.getTime()) / 1000));

        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remSeconds = seconds % 60;
        return `${minutes}m ${remSeconds}s`;
    }

    function formatDurationFromSeconds(sec: number | null) {
        if (!sec) return '--';
        const s = Math.round(sec);
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60);
        const rem = s % 60;
        if (m < 60) return `${m}m ${rem}s`;
        const h = Math.floor(m / 60);
        const remM = m % 60;
        return `${h}h ${remM}m`;
    }

    function getStatusVariant(status: string) {
        switch (status) {
            case 'COMPLETED': return 'success';
            case 'RUNNING': return 'blue';
            case 'FAILED': return 'error';
            default: return 'neutral';
        }
    }

    // Filtering
    const filteredJobs = $derived(
        jobs.filter(j => {
            if (typeFilter !== 'ALL' && j.job_type !== typeFilter) return false;
            if (statusFilter !== 'ALL' && j.status !== statusFilter) return false;
            if (searchQuery.trim()) {
                const q = searchQuery.trim().toLowerCase();
                if (!j.id.toString().includes(q) && !(j.job_type.toLowerCase().includes(q))) return false;
            }
            return true;
        })
    );

    const totalFiltered = $derived(
        statusFilter !== 'ALL' || typeFilter !== 'ALL' || searchQuery
            ? filteredJobs.length
            : totalJobs
    );

    const activeJobs = $derived(filteredJobs.filter(j => j.status === 'RUNNING' || j.status === 'PENDING'));
    const historicalJobs = $derived(filteredJobs.filter(j => j.status === 'COMPLETED' || j.status === 'FAILED'));

    // Date grouping for historical jobs
    function getDateGroup(dateStr: string | null | undefined) {
        if (!dateStr) return 'Older';
        const date = parseUTCDate(dateStr);
        if (!date) return 'Older';

        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const jobDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const diffDays = Math.floor((today.getTime() - jobDate.getTime()) / (1000 * 60 * 60 * 24));

        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Yesterday';
        if (diffDays < 7) return 'This week';
        return 'Older';
    }

    const groupedHistorical = $derived(() => {
        const groups: Record<string, AppApiCommonJobSchema[]> = {
            'Today': [],
            'Yesterday': [],
            'This week': [],
            'Older': []
        };

        for (const job of historicalJobs) {
            const group = getDateGroup(job.completed_at || job.created_at);
            groups[group].push(job);
        }

        return groups;
    });

    onMount(() => {
        loadInitialJobs();
        loadStats();
        pollInterval = setInterval(pollActiveJobs, POLL_SLOW);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });
</script>

<svelte:head>
    <title>Jobs - TapeHoard</title>
</svelte:head>

{#if selectedJobId}
    <JobDetailModal jobId={selectedJobId} onClear={() => selectedJobId = null} />
{/if}

<div class="flex flex-col gap-6 animate-in fade-in duration-700">
    <PageHeader
        title="Jobs"
        description="Real-time task monitoring & operational history"
        icon={Activity}
    >
        {#snippet actions()}
            <div class="flex items-center gap-2 px-3 py-1.5 bg-bg-primary/50 rounded-lg border border-border-color shadow-inner">
                <div class="w-2 h-2 rounded-full bg-blue-500 {activeJobs.length > 0 ? 'animate-pulse' : 'opacity-20'}"></div>
                <span class="text-[10px] font-medium text-text-secondary uppercase tracking-wider">
                    {activeJobs.length} active
                </span>
            </div>
            <Button variant="outline" size="icon" onclick={loadInitialJobs} disabled={loading}>
                <RotateCw size={16} class={loading ? 'animate-spin' : ''} />
            </Button>
        {/snippet}
    </PageHeader>

    <!-- Summary Statistics -->
    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card class="p-4 bg-bg-secondary border-border-color">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500">
                    <Activity size={16} />
                </div>
                <div>
                    <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Running</p>
                    <p class="text-lg font-bold mono text-text-primary">{stats?.running ?? 0}</p>
                </div>
            </div>
        </Card>

        <Card class="p-4 bg-bg-secondary border-border-color">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-green-500/10 rounded-lg text-green-500">
                    <ArrowUpRight size={16} />
                </div>
                <div>
                    <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Completed</p>
                    <p class="text-lg font-bold mono text-text-primary">{stats?.completed ?? 0}</p>
                </div>
            </div>
        </Card>

        <Card class="p-4 bg-bg-secondary border-border-color">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-error-color/10 rounded-lg text-error-color">
                    <StopCircle size={16} />
                </div>
                <div>
                    <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Failed</p>
                    <p class="text-lg font-bold mono text-text-primary">{stats?.failed ?? 0}</p>
                </div>
            </div>
        </Card>

        <Card class="p-4 bg-bg-secondary border-border-color">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-yellow-500/10 rounded-lg text-yellow-500">
                    <Clock size={16} />
                </div>
                <div>
                    <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Avg duration</p>
                    <p class="text-lg font-bold mono text-text-primary">{formatDurationFromSeconds(stats?.avg_duration_seconds ?? 0)}</p>
                </div>
            </div>
        </Card>

        <Card class="p-4 bg-bg-secondary border-border-color">
            <div class="flex items-center gap-3">
                <div class="p-2 bg-purple-500/10 rounded-lg text-purple-500">
                    <Filter size={16} />
                </div>
                <div>
                    <p class="text-[10px] font-medium text-text-secondary uppercase tracking-wide">Success rate</p>
                    <p class="text-lg font-bold mono text-text-primary">{stats?.success_rate ?? 0}%</p>
                </div>
            </div>
        </Card>
    </div>

    <div class="space-y-8">
        <!-- ACTIVE TASKS SECTION -->
        {#if statusFilter === 'ALL' || statusFilter === 'RUNNING' || statusFilter === 'PENDING'}
            <section class="space-y-4">
                <SectionHeader title="Running operations" icon={Play} iconColor="text-blue-500" />

                <div class="grid grid-cols-1 gap-4">
                    {#each activeJobs as job (job.id)}
                        <Card class="hover:border-blue-500/30 transition-all group overflow-hidden relative">
                            <div class="p-5 flex flex-col lg:flex-row lg:items-center gap-8 relative z-10">
                                <div class="flex items-center gap-4 min-w-[200px] cursor-pointer" onclick={() => openJobDetail(job.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && openJobDetail(job.id)}>
                                <div class="p-2.5 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20 shadow-inner">
                                    {#if job.job_type === 'SCAN'} <Search size={20} /> {:else if job.job_type === 'BACKUP'} <Play size={20} /> {:else} <RotateCw size={20} /> {/if}
                                </div>
                                    <div>
                                        <h3 class="font-bold text-text-primary text-base leading-none mb-2">{job.job_type.charAt(0) + job.job_type.slice(1).toLowerCase()} #{job.id}</h3>
                                        <StatusBadge variant={getStatusVariant(job.status)}>{job.status}</StatusBadge>
                                    </div>
                                </div>

                                <div class="flex-1 space-y-2.5">
                                    <div class="flex justify-between items-end">
                                        <span class="text-xs font-medium text-text-secondary truncate max-w-[400px]">
                                            {job.latest_log || job.current_task || 'Starting task...'}
                                        </span>
                                        <span class="text-xs font-semibold mono text-text-primary">{job.progress.toFixed(1)}%</span>
                                    </div>
                                    <ProgressBar value={job.progress} size="md" showGlow={true} />
                                </div>

                                <div class="grid grid-cols-2 gap-8 shrink-0">
                                    <div><span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Duration</span><span class="text-xs font-medium mono text-text-primary">{formatDuration(job.started_at)}</span></div>
                                    <div><span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Created</span><span class="text-xs font-medium mono text-text-primary">{formatLocalTime(job.created_at)}</span></div>
                                </div>

                                <Button variant="ghost" size="icon" class="h-9 w-9 text-error-color hover:bg-error-color/10" onclick={() => cancelJob(job.id)} title="Cancel task">
                                    <StopCircle size={18} />
                                </Button>
                            </div>
                        </Card>
                    {:else}
                        {#if statusFilter === 'ALL'}
                            <EmptyState
                                icon={Activity}
                                title="No active operations"
                                description="There are currently no tasks running on this station."
                            />
                        {/if}
                    {/each}
                </div>
            </section>
        {/if}

        <!-- Filters -->
        <div class="flex flex-wrap items-center gap-3 pt-2">
            <!-- Type filter -->
            <div class="flex items-center bg-bg-primary/50 rounded-lg border border-border-color overflow-hidden">
                {#each ['ALL', 'SCAN', 'BACKUP', 'RESTORE'] as type}
                    <button
                        class={cn(
                            "px-3 py-1.5 text-[11px] font-medium transition-colors",
                            typeFilter === type
                                ? "bg-blue-500/10 text-blue-400"
                                : "text-text-secondary hover:text-text-primary"
                        )}
                        onclick={() => { typeFilter = type; }}
                    >{type}</button>
                {/each}
            </div>

            <!-- Status filter -->
            <div class="flex items-center bg-bg-primary/50 rounded-lg border border-border-color overflow-hidden">
                {#each ['ALL', 'RUNNING', 'COMPLETED', 'FAILED', 'PENDING'] as status}
                    <button
                        class={cn(
                            "px-3 py-1.5 text-[11px] font-medium transition-colors",
                            statusFilter === status
                                ? "bg-blue-500/10 text-blue-400"
                                : "text-text-secondary hover:text-text-primary"
                        )}
                        onclick={() => { statusFilter = status; }}
                    >{status}</button>
                {/each}
            </div>

            <!-- Search by ID -->
            <div class="relative flex-1 min-w-[240px]">
                <Search size={14} class="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary opacity-40" />
                <input
                    type="text"
                    placeholder="Search by ID or type..."
                    bind:value={searchQuery}
                    class="w-full pl-9 pr-3 py-1.5 text-xs bg-bg-primary/50 border border-border-color rounded-lg text-text-primary placeholder:text-text-secondary/40 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20"
                />
            </div>

            <!-- Reset filters -->
            {#if typeFilter !== 'ALL' || statusFilter !== 'ALL' || searchQuery}
                <button
                    class="px-3 py-1.5 text-[11px] font-medium text-text-secondary hover:text-text-primary transition-colors"
                    onclick={() => { typeFilter = 'ALL'; statusFilter = 'ALL'; searchQuery = ''; }}
                >
                    Reset
                </button>
            {/if}
        </div>

        <!-- HISTORICAL TASKS SECTION -->
        {#if statusFilter === 'ALL' || statusFilter === 'COMPLETED' || statusFilter === 'FAILED'}
            <section class="space-y-4">
                <SectionHeader title="Execution history" icon={History} iconColor="text-text-secondary" />

                <div class="grid grid-cols-1 gap-3">
                    {#each Object.entries(groupedHistorical()) as [groupName, groupJobs]}
                        {#if groupJobs.length > 0}
                            <div class="space-y-2">
                                <h4 class="text-xs font-semibold text-text-secondary uppercase tracking-wider px-1">{groupName}</h4>
                                {#each groupJobs as job (job.id)}
                                    <Card class="px-5 py-3 bg-bg-secondary/40 border-border-color/40 hover:bg-bg-secondary transition-colors group">
                                        <div class="flex items-center gap-4">
                                            <div class="w-9 h-9 flex items-center justify-center rounded-lg bg-bg-primary border border-border-color/40 text-text-secondary group-hover:text-text-primary transition-colors shrink-0">
                                                {#if job.job_type === 'SCAN'} <Search size={16} /> {:else if job.job_type === 'BACKUP'} <Play size={16} /> {:else} <RotateCw size={16} /> {/if}
                                            </div>

                                            <div class="flex-1 min-w-0">
                                                <div class="flex items-center gap-2">
                                                    <button class="text-sm font-semibold text-text-primary hover:text-blue-400 transition-colors" onclick={() => openJobDetail(job.id)}>
                                                        {job.job_type.charAt(0) + job.job_type.slice(1).toLowerCase()} #{job.id}
                                                    </button>
                                                    <StatusBadge variant={getStatusVariant(job.status)}>{job.status}</StatusBadge>
                                                </div>
                                                <p class="text-xs text-text-secondary mt-0.5 opacity-60 truncate">{job.latest_log || job.error_message || job.current_task || 'Finished successfully'}</p>
                                            </div>

                                            <div class="flex items-center gap-6 shrink-0">
                                                <div class="text-right">
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block">Duration</span>
                                                    <span class="text-xs font-medium mono text-text-primary">{formatDuration(job.started_at, job.completed_at)}</span>
                                                </div>
                                                <div class="text-right">
                                                    <span class="text-[10px] font-medium text-text-secondary opacity-40 block">{job.status === 'COMPLETED' ? 'Completed' : job.status === 'FAILED' ? 'Failed' : 'Created'}</span>
                                                    <span class="text-xs font-medium mono text-text-primary">{formatLocalTime(job.completed_at || job.started_at || job.created_at)}</span>
                                                </div>
                                                <div class="flex items-center gap-1">
                                                    {#if job.status === 'FAILED'}
                                                        <Button variant="ghost" size="icon" class="h-8 w-8 text-orange-400 hover:bg-orange-400/10 opacity-40 group-hover:opacity-100 transition-opacity" onclick={() => retryJob(job.id)} title="Retry">
                                                            <RotateCcw size={14} />
                                                        </Button>
                                                    {/if}
                                                    <Button variant="ghost" size="icon" class="h-8 w-8 opacity-20 group-hover:opacity-100 transition-opacity" onclick={() => openJobDetail(job.id)}>
                                                        <ExternalLink size={14} />
                                                    </Button>
                                                </div>
                                            </div>
                                        </div>
                                    </Card>
                                {/each}
                            </div>
                        {/if}
                    {/each}

                    {#if historicalJobs.length === 0 && (statusFilter === 'ALL' || statusFilter === 'COMPLETED' || statusFilter === 'FAILED')}
                        <EmptyState
                            icon={History}
                            title="No completed jobs"
                            description="Historical job records will appear here once tasks finish."
                        />
                    {/if}

                    {#if filteredJobs.length < totalFiltered}
                        <Button
                            variant="outline"
                            class="w-full h-11 mt-4 border-dashed border-2 border-border-color hover:border-blue-500/50 text-text-secondary hover:text-blue-400 transition-all"
                            onclick={loadMore}
                            disabled={loadingMore}
                        >
                            {#if loadingMore}
                                <RotateCw size={16} class="mr-2 animate-spin" /> Fetching...
                            {:else}
                                <ChevronDown size={16} class="mr-2" /> Load more ({filteredJobs.length} of {totalFiltered})
                            {/if}
                        </Button>
                    {/if}
                </div>
            </section>
        {/if}
    </div>
</div>
