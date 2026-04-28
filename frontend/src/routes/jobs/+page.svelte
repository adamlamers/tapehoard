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
        Save
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import JobDetailModal from '$lib/components/JobDetailModal.svelte';
    import {
        listJobsSystemJobsGet,
        getJobsCountSystemJobsCountGet,
        cancelJobSystemJobsJobIdCancelPost,
        type JobSchema
    } from '$lib/api';
    import { cn, formatLocalTime, parseUTCDate } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let jobs = $state<JobSchema[]>([]);
    let totalJobs = $state(0);
    let loading = $state(true);
    let loadingMore = $state(false);
    let pollInterval: any;
    let offset = $state(0);
    let selectedJobId = $state<number | null>(null);
    const LIMIT = 20;

    async function loadInitialJobs() {
        loading = true;
        try {
            const [jobsRes, countRes] = await Promise.all([
                listJobsSystemJobsGet({ query: { limit: LIMIT, offset: 0 } }),
                getJobsCountSystemJobsCountGet()
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
            const response = await listJobsSystemJobsGet({
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
        const hasActive = jobs.some(j => j.status === 'RUNNING' || j.status === 'PENDING');
        if (!hasActive && offset > 0) return;

        try {
            const response = await listJobsSystemJobsGet({
                query: { limit: LIMIT, offset: 0 }
            });
            if (response.data) {
                const updated = response.data;
                const rest = jobs.slice(LIMIT);
                jobs = [...updated, ...rest];
            }

            const countRes = await getJobsCountSystemJobsCountGet();
            if (countRes.data) totalJobs = (countRes.data as any).count;
        } catch (error) {
            // Silently fail polling
        }
    }

    async function cancelJob(jobId: number) {
        try {
            await cancelJobSystemJobsJobIdCancelPost({
                path: { job_id: jobId },
                throwOnError: true
            });
            toast.info(`Cancellation requested for Job #${jobId}`);
            pollActiveJobs();
        } catch (error) {
            toast.error("Failed to cancel job");
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

    function getStatusColor(status: string) {
        switch (status) {
            case 'COMPLETED': return 'text-success-color bg-success-color/5 border-success-color/20';
            case 'RUNNING': return 'text-blue-500 bg-blue-500/5 border-blue-500/20';
            case 'FAILED': return 'text-error-color bg-error-color/5 border-error-color/20';
            default: return 'text-text-secondary bg-bg-primary/50 border-border-color/50';
        }
    }

    onMount(() => {
        loadInitialJobs();
        pollInterval = setInterval(pollActiveJobs, 3000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    const activeJobs = $derived(jobs.filter(j => j.status === 'RUNNING' || j.status === 'PENDING'));
    const historicalJobs = $derived(jobs.filter(j => j.status === 'COMPLETED' || j.status === 'FAILED'));
</script>

<svelte:head>
    <title>Jobs - TapeHoard</title>
</svelte:head>

{#if selectedJobId}
    <JobDetailModal jobId={selectedJobId} onClear={() => selectedJobId = null} />
{/if}

<div class="flex flex-col gap-8 animate-in fade-in duration-700">
    <!-- HEADER -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Activity class="text-blue-500" size={28} />
                Jobs
            </h1>
            <p class="text-xs font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Real-time task monitoring & operational history
            </p>
        </div>

        <div class="flex items-center gap-4 z-10">
            <div class="flex items-center gap-2 px-4 py-2 bg-bg-primary/50 rounded-lg border border-border-color shadow-inner">
                <div class="w-2 h-2 rounded-full bg-blue-500 {activeJobs.length > 0 ? 'animate-pulse' : 'opacity-20'}"></div>
                <span class="text-3xs font-black uppercase tracking-widest text-text-secondary">
                    {activeJobs.length} Active Tasks
                </span>
            </div>
            <Button variant="outline" size="icon" class="h-10 w-10 border-border-color" onclick={loadInitialJobs} disabled={loading}>
                <RotateCw size={18} class={loading ? 'animate-spin' : ''} />
            </Button>
        </div>
    </header>

    <div class="space-y-12">
        <!-- ACTIVE TASKS SECTION -->
        <section class="space-y-6">
            <div class="flex items-center gap-3 px-2">
                <div class="p-1.5 bg-blue-500/10 rounded-md text-blue-500"><Play size={16} /></div>
                <h2 class="text-2xs font-black uppercase tracking-[0.2em] text-text-primary">Running Operations</h2>
                <div class="h-px flex-1 bg-gradient-to-r from-border-color/60 to-transparent"></div>
            </div>

            <div class="grid grid-cols-1 gap-4">
                {#each activeJobs as job (job.id)}
                    <Card class="p-6 bg-bg-secondary border-border-color hover:border-blue-500/30 transition-all group overflow-hidden relative">
                        <div class="flex flex-col lg:flex-row lg:items-center gap-8 relative z-10">
                            <div class="flex items-center gap-4 min-w-[200px]" onclick={() => openJobDetail(job.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && openJobDetail(job.id)}>
                                <div class="p-3 bg-blue-500/10 rounded-xl text-blue-500 border border-blue-500/20 shadow-inner">
                                    {#if job.job_type === 'SCAN'} <Search size={22} /> {:else if job.job_type === 'BACKUP'} <Play size={22} /> {:else} <RotateCw size={22} /> {/if}
                                </div>
                                <div>
                                    <h3 class="font-black text-text-primary uppercase tracking-tighter text-lg leading-none mb-2">{job.job_type} #{job.id}</h3>
                                    <span class="px-2 py-0.5 rounded-full border text-4xs font-black uppercase tracking-widest {getStatusColor(job.status)}">{job.status}</span>
                                </div>
                            </div>

                            <div class="flex-1 space-y-3">
                                <div class="flex justify-between items-end">
                                    <span class="text-3xs font-black uppercase tracking-widest text-text-secondary truncate max-w-[400px]">
                                        {job.current_task || 'Starting task...'}
                                    </span>
                                    <span class="text-xs font-bold mono text-text-primary">{job.progress.toFixed(1)}%</span>
                                </div>
                                <div class="w-full bg-bg-primary h-2 rounded-full border border-border-color overflow-hidden">
                                    <div class="bg-blue-500 h-full transition-all duration-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]" style="width: {job.progress}%"></div>
                                </div>
                            </div>

                            <div class="grid grid-cols-2 gap-8 shrink-0">
                                <div><span class="text-4xs font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Duration</span><span class="text-xs font-bold mono text-text-primary">{formatDuration(job.started_at)}</span></div>
                                <div><span class="text-4xs font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-1">Created</span><span class="text-xs font-bold mono text-text-primary">{formatLocalTime(job.created_at)}</span></div>
                            </div>

                            <Button variant="ghost" size="icon" class="h-10 w-10 text-error-color hover:bg-error-color/10" onclick={() => cancelJob(job.id)} title="Cancel Task">
                                <StopCircle size={20} />
                            </Button>
                        </div>
                    </Card>
                {:else}
                    <div class="py-12 border-2 border-dashed border-border-color rounded-2xl flex flex-col items-center justify-center opacity-20">
                        <Activity size={48} class="mb-2" />
                        <p class="text-3xs font-black uppercase tracking-widest">No active operations</p>
                    </div>
                {/each}
            </div>
        </section>

        <!-- HISTORICAL TASKS SECTION -->
        <section class="space-y-6">
            <div class="flex items-center gap-3 px-2">
                <div class="p-1.5 bg-text-secondary/10 rounded-md text-text-secondary"><History size={16} /></div>
                <h2 class="text-2xs font-black uppercase tracking-[0.2em] text-text-secondary">Execution History</h2>
                <div class="h-px flex-1 bg-gradient-to-r from-border-color/30 to-transparent"></div>
            </div>

            <div class="grid grid-cols-1 gap-3">
                {#each historicalJobs as job (job.id)}
                    <Card class="px-6 py-4 bg-bg-secondary/40 border-border-color/40 hover:bg-bg-secondary transition-colors group">
                        <div class="flex items-center gap-6">
                            <div class="w-10 h-10 flex items-center justify-center rounded-lg bg-bg-primary border border-border-color/40 text-text-secondary group-hover:text-text-primary transition-colors">
                                {#if job.job_type === 'SCAN'} <Search size={18} /> {:else if job.job_type === 'BACKUP'} <Play size={18} /> {:else} <RotateCw size={18} /> {/if}
                            </div>

                            <div class="flex-1">
                                <div class="flex items-center gap-3">
                                    <span class="text-sm font-black text-text-primary uppercase tracking-tight">{job.job_type} JOB #{job.id}</span>
                                    <span class="px-2 py-0.5 rounded border text-5xs font-black uppercase tracking-widest {getStatusColor(job.status)}">{job.status}</span>
                                </div>
                                <p class="text-3xs text-text-secondary mt-1 opacity-60 truncate">{job.error_message || job.current_task || 'Finished successfully'}</p>
                            </div>

                            <div class="grid grid-cols-3 gap-12 shrink-0">
                                <div><span class="text-5xs font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-0.5">Duration</span><span class="text-2xs font-bold mono text-text-primary">{formatDuration(job.started_at, job.completed_at)}</span></div>
                                <div><span class="text-5xs font-black uppercase tracking-widest text-text-secondary opacity-40 block mb-0.5">Completed</span><span class="text-2xs font-bold mono text-text-primary">{formatLocalTime(job.completed_at)}</span></div>
                                <div class="flex items-center justify-end">
                                    <Button variant="ghost" size="icon" class="h-8 w-8 opacity-20 group-hover:opacity-100" onclick={() => openJobDetail(job.id)}>
                                        <ExternalLink size={14} />
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </Card>
                {/each}

                {#if jobs.length < totalJobs}
                    <Button
                        variant="outline"
                        class="w-full h-12 mt-4 border-dashed border-2 border-border-color hover:border-action-color/50 text-text-secondary hover:text-action-color transition-all"
                        onclick={loadMore}
                        disabled={loadingMore}
                    >
                        {#if loadingMore}
                            <RotateCw size={16} class="mr-2 animate-spin" /> Fetching more records...
                        {:else}
                            <ChevronDown size={16} class="mr-2" /> Load More (Showing {jobs.length} of {totalJobs})
                        {/if}
                    </Button>
                {/if}
            </div>
        </section>
    </div>
</div>
