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
    import PageHeader from '$lib/components/ui/PageHeader.svelte';
    import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
    import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
    import ProgressBar from '$lib/components/ui/ProgressBar.svelte';
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

    function getStatusVariant(status: string) {
        switch (status) {
            case 'COMPLETED': return 'success';
            case 'RUNNING': return 'blue';
            case 'FAILED': return 'error';
            default: return 'neutral';
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

    <div class="space-y-10">
        <!-- ACTIVE TASKS SECTION -->
        <section class="space-y-4">
            <SectionHeader title="Running operations" icon={Play} iconColor="text-blue-500" />

            <div class="grid grid-cols-1 gap-4">
                {#each activeJobs as job (job.id)}
                    <Card class="hover:border-blue-500/30 transition-all group overflow-hidden relative">
                        <div class="p-5 flex flex-col lg:flex-row lg:items-center gap-8 relative z-10">
                            <div class="flex items-center gap-4 min-w-[200px]" onclick={() => openJobDetail(job.id)} role="button" tabindex="0" onkeydown={(e) => e.key === 'Enter' && openJobDetail(job.id)}>
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
                                        {job.current_task || 'Starting task...'}
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
                    <div class="py-12 border-2 border-dashed border-border-color rounded-2xl flex flex-col items-center justify-center opacity-20">
                        <Activity size={40} class="mb-2 text-blue-500" />
                        <p class="text-xs font-medium">No active operations</p>
                    </div>
                {/each}
            </div>
        </section>

        <!-- HISTORICAL TASKS SECTION -->
        <section class="space-y-4">
            <SectionHeader title="Execution history" icon={History} iconColor="text-text-secondary" />

            <div class="grid grid-cols-1 gap-3">
                {#each historicalJobs as job (job.id)}
                    <Card class="px-6 py-4 bg-bg-secondary/40 border-border-color/40 hover:bg-bg-secondary transition-colors group">
                        <div class="flex items-center gap-6">
                            <div class="w-10 h-10 flex items-center justify-center rounded-lg bg-bg-primary border border-border-color/40 text-text-secondary group-hover:text-text-primary transition-colors">
                                {#if job.job_type === 'SCAN'} <Search size={18} /> {:else if job.job_type === 'BACKUP'} <Play size={18} /> {:else} <RotateCw size={18} /> {/if}
                            </div>

                            <div class="flex-1">
                                <div class="flex items-center gap-3">
                                    <span class="text-sm font-semibold text-text-primary uppercase tracking-tight">{job.job_type} JOB #{job.id}</span>
                                    <StatusBadge variant={getStatusVariant(job.status)}>{job.status}</StatusBadge>
                                </div>
                                <p class="text-xs text-text-secondary mt-1 opacity-60 truncate">{job.error_message || job.current_task || 'Finished successfully'}</p>
                            </div>

                            <div class="grid grid-cols-3 gap-12 shrink-0">
                                <div><span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Duration</span><span class="text-xs font-medium mono text-text-primary">{formatDuration(job.started_at, job.completed_at)}</span></div>
                                <div><span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-0.5">Completed</span><span class="text-xs font-medium mono text-text-primary">{formatLocalTime(job.completed_at)}</span></div>
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
                        class="w-full h-11 mt-4 border-dashed border-2 border-border-color hover:border-action-color/50 text-text-secondary hover:text-action-color transition-all"
                        onclick={loadMore}
                        disabled={loadingMore}
                    >
                        {#if loadingMore}
                            <RotateCw size={16} class="mr-2 animate-spin" /> Fetching more records...
                        {:else}
                            <ChevronDown size={16} class="mr-2" /> Load more (Showing {jobs.length} of {totalJobs})
                        {/if}
                    </Button>
                {/if}
            </div>
        </section>
    </div>
</div>
