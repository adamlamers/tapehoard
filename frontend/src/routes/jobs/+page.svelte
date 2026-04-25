<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import {
        Activity,
        Clock,
        RotateCw,
        Search,
        ExternalLink,
        Play,
        StopCircle
    } from 'lucide-svelte';
    import { Card } from '$lib/components/ui/card';
    import { Button } from '$lib/components/ui/button';
    import { listJobsSystemJobsGet, cancelJobSystemJobsJobIdCancelPost, type JobSchema } from '$lib/api';
    import { cn, formatLocalTime, parseUTCDate } from '$lib/utils';
    import { toast } from 'svelte-sonner';

    let jobs = $state<JobSchema[]>([]);
    let loading = $state(true);
    let pollInterval: any;

    async function loadJobs() {
        try {
            const response = await listJobsSystemJobsGet();
            if (response.data) {
                jobs = response.data;
            }
        } catch (error) {
            console.error("Failed to load jobs:", error);
        } finally {
            loading = false;
        }
    }

    async function cancelJob(jobId: number) {
        try {
            await cancelJobSystemJobsJobIdCancelPost({
                path: { job_id: jobId }
            });
            toast.info(`Cancellation requested for Job #${jobId}`);
            await loadJobs();
        } catch (error) {
            toast.error("Failed to cancel job");
        }
    }

    onMount(() => {
        loadJobs();
        pollInterval = setInterval(loadJobs, 2000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });

    function getStatusColor(status: string) {
        switch (status) {
            case 'COMPLETED': return 'text-success-color bg-success-color/10 border-success-color/20';
            case 'RUNNING': return 'text-blue-500 bg-blue-500/10 border-blue-500/20';
            case 'FAILED': return 'text-error-color bg-error-color/10 border-error-color/20';
            case 'PENDING': return 'text-text-secondary bg-bg-primary border-border-color';
            default: return 'text-text-secondary bg-bg-primary';
        }
    }

    function formatDuration(start?: string | null, end?: string | null) {
        const startDate = parseUTCDate(start);
        if (!startDate) return '--';

        const endDate = end ? parseUTCDate(end) : new Date();
        if (!endDate) return '--';

        const seconds = Math.max(0, Math.floor((endDate.getTime() - startDate.getTime()) / 1000));

        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remSeconds = seconds % 60;
        return `${minutes}m ${remSeconds}s`;
    }
</script>

<svelte:head>
    <title>System Activity - TapeHoard</title>
</svelte:head>

<div class="space-y-8 animate-in fade-in duration-700">
    <!-- HEADER -->
    <header class="flex justify-between items-center bg-bg-secondary px-8 py-5 rounded-xl border border-border-color shadow-2xl relative overflow-hidden">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>
        <div class="relative z-10">
            <h1 class="text-2xl font-black uppercase tracking-tighter text-text-primary flex items-center gap-3">
                <Activity class="text-blue-500" size={28} />
                System Activity
            </h1>
            <p class="text-[12px] font-bold uppercase tracking-widest text-text-secondary mt-1 opacity-80">
                Real-time task monitoring & operational history
            </p>
        </div>

        <div class="flex gap-4 z-10">
            <div class="flex items-center gap-2 px-4 py-2 bg-bg-primary rounded-lg border border-border-color shadow-inner">
                <div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary">
                    {jobs.filter(j => j.status === 'RUNNING').length} Active Tasks
                </span>
            </div>
        </div>
    </header>

    {#if loading && jobs.length === 0}
        <div class="flex flex-col items-center justify-center py-24 gap-4 opacity-50">
            <RotateCw size={48} class="animate-spin text-blue-500" />
            <span class="text-xs font-black uppercase tracking-widest">Hydrating Task Pipeline...</span>
        </div>
    {:else}
        <div class="grid grid-cols-1 gap-4">
            {#each jobs as job (job.id)}
                <Card class="p-6 bg-bg-secondary border-border-color hover:border-blue-500/30 transition-all group overflow-hidden relative">
                    <div class="flex flex-col md:flex-row md:items-center gap-6 relative z-10">
                        <!-- Type & Status -->
                        <div class="flex items-center gap-4 min-w-[240px]">
                            <div class={cn(
                                "p-3 rounded-xl border shadow-inner shrink-0",
                                job.status === 'RUNNING' ? 'bg-blue-500/10 text-blue-500 border-blue-500/20' : 'bg-bg-primary text-text-secondary border-border-color/50'
                            )}>
                                {#if job.job_type === 'SCAN'}
                                    <Search size={24} />
                                {:else if job.job_type === 'BACKUP'}
                                    <Play size={24} />
                                {:else}
                                    <RotateCw size={24} />
                                {/if}
                            </div>
                            <div>
                                <h3 class="font-black text-text-primary uppercase tracking-tighter text-lg leading-none mb-2">
                                    {job.job_type} JOB #{job.id}
                                </h3>
                                <div class={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2", getStatusColor(job.status))}>
                                    <span class="font-black uppercase tracking-widest text-[9px]">{job.status}</span>
                                </div>
                            </div>
                        </div>

                        <!-- Progress Section -->
                        <div class="flex-1 space-y-3">
                            <div class="flex justify-between items-end">
                                <span class="text-[10px] font-black uppercase tracking-widest text-text-secondary truncate max-w-[300px]">
                                    {job.current_task || 'Waiting in queue...'}
                                </span>
                                {#if job.job_type !== 'SCAN' || job.status === 'COMPLETED'}
                                    <span class="text-xs font-bold mono text-text-primary">
                                        {job.status === 'COMPLETED' ? '100.0' : job.progress.toFixed(1)}%
                                    </span>
                                {/if}
                            </div>
                            {#if job.job_type !== 'SCAN' || job.status !== 'RUNNING'}
                                <div class="w-full bg-bg-primary h-2.5 rounded-full border border-border-color shadow-inner overflow-hidden">
                                    <div
                                        class={cn(
                                            "h-full transition-all duration-500",
                                            job.status === 'RUNNING' ? 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]' :
                                            job.status === 'FAILED' ? 'bg-error-color' : 'bg-success-color'
                                        )}
                                        style="width: {job.status === 'COMPLETED' ? 100 : job.progress}%"
                                    ></div>
                                </div>
                            {:else}
                                <div class="flex items-center gap-3 h-2.5">
                                    <div class="flex-1 bg-bg-primary h-1 rounded-full border border-border-color/30 relative overflow-hidden">
                                        <div class="absolute inset-0 bg-blue-500/20 animate-pulse"></div>
                                    </div>
                                    <span class="text-[9px] font-black uppercase tracking-widest text-blue-400 whitespace-nowrap animate-pulse">
                                        Streaming Discovery
                                    </span>
                                </div>
                            {/if}
                        </div>

                        <!-- Timing Stats -->
                        <div class="grid grid-cols-2 gap-8 min-w-[200px]">
                            <div>
                                <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Duration</span>
                                <div class="flex items-center gap-1.5 text-xs font-bold text-text-primary mono">
                                    <Clock size={12} class="text-text-secondary" />
                                    {formatDuration(job.started_at, job.completed_at)}
                                </div>
                            </div>
                            <div>
                                <span class="text-[9px] font-black uppercase tracking-widest text-text-secondary opacity-50 block mb-1">Created</span>
                                <div class="text-xs font-bold text-text-primary mono">
                                    {formatLocalTime(job.created_at)}
                                </div>
                            </div>
                        </div>

                        <!-- Actions -->
                        <div class="flex items-center gap-2">
                            {#if job.status === 'RUNNING' || job.status === 'PENDING'}
                                <button
                                    class="text-error-color hover:bg-error-color/10 font-black uppercase tracking-widest text-[9px] px-3 h-8 rounded-lg border border-transparent hover:border-error-color/20 transition-all flex items-center"
                                    onclick={() => cancelJob(job.id)}
                                >
                                    <StopCircle size={14} class="mr-1.5" /> Cancel Task
                                </button>
                            {/if}
                            <Button variant="ghost" size="icon" class="h-8 w-8 hover:bg-white/5">
                                <ExternalLink size={16} class="text-text-secondary group-hover:text-text-primary transition-colors" />
                            </Button>
                        </div>
                    </div>

                    {#if job.error_message}
                        <div class="mt-4 p-4 bg-error-color/5 border border-dashed border-error-color/20 rounded-lg flex gap-3 items-start animate-in slide-in-from-top-2">
                            <RotateCw size={16} class="text-error-color shrink-0 mt-0.5" />
                            <p class="text-[11px] font-medium text-error-color/80 leading-relaxed italic">
                                {job.error_message}
                            </p>
                        </div>
                    {/if}

                    {#if job.status === 'RUNNING'}
                        <div class="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 blur-3xl rounded-full -mr-12 -mt-12 animate-pulse"></div>
                    {/if}
                </Card>
            {:else}
                <div class="flex flex-col items-center justify-center py-24 border-2 border-dashed border-border-color rounded-2xl opacity-30">
                    <Activity size={48} class="mb-4" />
                    <p class="text-sm font-black uppercase tracking-widest">No historical tasks found.</p>
                </div>
            {/each}
        </div>
    {/if}
</div>
