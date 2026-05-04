<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { X, Activity, Search, Play, RotateCw, Clock, CheckCircle2, AlertCircle, FileText, Database, HardDrive, MapPin, ExternalLink, ArrowRight, Terminal } from 'lucide-svelte';
    import { Button } from './ui/button';
    import { Card } from './ui/card';
    import Dialog from './ui/Dialog.svelte';
    import { getJob, getJobLogs, type AppApiSystemJobSchema } from '$lib/api';
    import { cn, formatLocalTime, formatLocalDateTime, parseUTCDate } from '$lib/utils';
    import { POLL_FAST } from '$lib/config';

    let { jobId, onClear } = $props<{
        jobId: number;
        onClear: () => void;
    }>();

    let job = $state<AppApiSystemJobSchema | null>(null);
    let logs = $state<{ id: number; message: string; timestamp: string }[]>([]);
    let loading = $state(true);
    let pollInterval: any;

    async function loadJob() {
        loading = true;
        try {
            const [jobRes, logsRes] = await Promise.all([
                getJob({ path: { job_id: jobId } }),
                getJobLogs({ path: { job_id: jobId } })
            ]);
            if (jobRes.data) job = jobRes.data;
            if (logsRes.data) logs = logsRes.data;
        } catch (error) {
            console.error("Failed to load job details:", error);
        } finally {
            loading = false;
        }
    }

    async function pollJob() {
        if (!job || (job.status !== 'RUNNING' && job.status !== 'PENDING')) return;

        try {
            const [jobRes, logsRes] = await Promise.all([
                getJob({ path: { job_id: jobId } }),
                getJobLogs({ path: { job_id: jobId } })
            ]);
            if (jobRes.data) {
                const wasRunning = job.status === 'RUNNING' || job.status === 'PENDING';
                job = jobRes.data;
                if (!wasRunning && job.status !== 'RUNNING' && job.status !== 'PENDING') {
                    // Job just finished, stop polling
                    if (pollInterval) clearInterval(pollInterval);
                }
            }
            if (logsRes.data) logs = logsRes.data;
        } catch (error) {
            // Silently fail
        }
    }

    function formatDuration(start?: string | null, end?: string | null) {
        const startDate = parseUTCDate(start);
        if (!startDate) return '--';

        const endDate = parseUTCDate(end) || new Date();
        const seconds = Math.max(0, Math.floor((endDate.getTime() - startDate.getTime()) / 1000));

        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const remSeconds = seconds % 60;
        return `${minutes}m ${remSeconds}s`;
    }

    function formatLogTime(timestamp: string) {
        const date = parseUTCDate(timestamp);
        if (!date) return '--';
        return date.toLocaleTimeString();
    }

    onMount(() => {
        loadJob();
        pollInterval = setInterval(pollJob, POLL_FAST);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });
</script>

<Dialog show={true} onClose={onClear} ariaLabelledBy="modal-title">
    <Card class="w-[800px] max-h-[90vh] overflow-hidden flex flex-col shadow-2xl">
        {#if loading}
            <div class="flex-1 flex flex-col items-center justify-center gap-4 py-24">
                <RotateCw size={48} class="animate-spin text-blue-500" />
                <span class="text-xs font-medium text-text-secondary">Loading details...</span>
            </div>
        {:else if job}
            <!-- Header -->
            <header class="p-6 border-b border-border-color bg-bg-tertiary/30 relative overflow-hidden">
                <div class="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent pointer-events-none"></div>

                <div class="flex justify-between items-start relative z-10">
                    <div class="flex items-center gap-5">
                        <div class="p-3 bg-blue-500/10 rounded-2xl text-blue-500 border border-blue-500/20 shadow-inner">
                            {#if job.job_type === 'SCAN'} <Search size={24} /> {:else if job.job_type === 'BACKUP'} <Play size={24} /> {:else} <RotateCw size={24} /> {/if}
                        </div>
                        <div>
                            <div class="flex items-center gap-3 mb-1">
                                <h2 id="modal-title" class="text-xl font-bold text-text-primary">{job.job_type.charAt(0) + job.job_type.slice(1).toLowerCase()} job #{job.id}</h2>
                                <span class={cn(
                                    "px-2.5 py-0.5 rounded-full border text-[10px] font-medium uppercase tracking-wider",
                                    job.status === 'COMPLETED' ? 'text-success-color border-success-color/20 bg-success-color/5' :
                                    job.status === 'FAILED' ? 'text-error-color border-error-color/20 bg-error-color/5' :
                                    'text-blue-400 border-blue-500/20 bg-blue-500/5'
                                )}>{job.status}</span>
                                {#if job.status === 'RUNNING' || job.status === 'PENDING'}
                                    <span class="text-[10px] font-medium mono text-blue-400 ml-1">{job.progress.toFixed(1)}%</span>
                                {/if}
                            </div>
                            <p class="text-xs text-text-secondary opacity-60">Execution timeline & artifacts</p>
                        </div>
                    </div>
                    <Button variant="ghost" size="icon" class="hover:bg-white/5 h-9 w-9" onclick={onClear}><X size={20} /></Button>
                </div>
            </header>

            <div class="flex-1 overflow-y-auto p-6 space-y-8">
                <!-- Operational Summary -->
                <div class="grid grid-cols-3 gap-6">
                    <div class="p-4 bg-bg-primary/40 border border-border-color/60 rounded-xl">
                        <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-1 uppercase tracking-wider">Total duration</span>
                        <div class="flex items-center gap-2">
                            <Clock size={14} class="text-blue-400" />
                            <span class="text-base font-bold text-text-primary mono">{formatDuration(job.started_at, job.completed_at)}</span>
                        </div>
                    </div>
                    <div class="p-4 bg-bg-primary/40 border border-border-color/60 rounded-xl">
                        <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-1 uppercase tracking-wider">Start time</span>
                        <span class="text-sm font-semibold text-text-primary mono">{formatLocalDateTime(job.started_at)}</span>
                    </div>
                    <div class="p-4 bg-bg-primary/40 border border-border-color/60 rounded-xl">
                        <span class="text-[10px] font-medium text-text-secondary opacity-40 block mb-1 uppercase tracking-wider">End time</span>
                        <span class="text-sm font-semibold text-text-primary mono">{formatLocalDateTime(job.completed_at) || '--'}</span>
                    </div>
                </div>

                <!-- Progress bar for running jobs -->
                {#if job.status === 'RUNNING' || job.status === 'PENDING'}
                    <div class="space-y-2">
                        <div class="flex justify-between text-xs">
                            <span class="text-text-secondary">{job.latest_log || job.current_task || 'Starting...'}</span>
                            <span class="mono font-medium text-text-primary">{job.progress.toFixed(1)}%</span>
                        </div>
                        <div class="w-full bg-bg-primary h-2 rounded-full overflow-hidden">
                            <div class="bg-blue-500 h-full transition-all duration-1000" style="width: {job.progress}%"></div>
                        </div>
                    </div>
                {/if}

                <!-- Execution Log -->
                <div class="space-y-4">
                    <div class="flex items-center gap-2 px-1">
                        <Terminal size={14} class="text-text-secondary opacity-50" />
                        <h3 class="text-[10px] font-medium text-text-secondary uppercase tracking-wider">Execution log</h3>
                        {#if job.status === 'RUNNING' || job.status === 'PENDING'}
                            <div class="ml-auto w-2 h-2 rounded-full bg-blue-500 animate-pulse"></div>
                        {/if}
                    </div>

                    {#if logs.length > 0}
                        <div class="bg-bg-primary border border-border-color/60 rounded-xl overflow-hidden">
                            <div class="max-h-[300px] overflow-y-auto font-mono text-xs p-4 space-y-1">
                                {#each logs as log (log.id)}
                                    <div class="flex gap-3 leading-relaxed">
                                        <span class="text-text-secondary/40 shrink-0 select-none">{formatLogTime(log.timestamp)}</span>
                                        <span class="text-text-primary/80 whitespace-pre-wrap break-words">{log.message}</span>
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {:else if job.error_message}
                        <div class="p-5 rounded-xl border mono text-xs leading-relaxed bg-error-color/5 border-error-color/20 text-error-color/90">
                            <div class="flex gap-3 items-start">
                                <AlertCircle size={16} class="shrink-0 mt-0.5" />
                                <div>
                                    <span class="font-bold uppercase tracking-wider block mb-2 text-[10px]">Critical error</span>
                                    {job.error_message}
                                </div>
                            </div>
                        </div>
                    {:else}
                        <div class="p-5 rounded-xl border mono text-xs leading-relaxed bg-bg-primary border-border-color/60 text-text-primary/80">
                            <div class="flex gap-3 items-start text-success-color">
                                <CheckCircle2 size={16} class="shrink-0 mt-0.5" />
                                <div>
                                    <span class="font-bold uppercase tracking-wider block mb-2 text-[10px]">Task summary</span>
                                    {job.current_task || 'Process completed successfully with zero hardware interrupts.'}
                                </div>
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Next Steps / Metadata -->
                <div class="p-5 bg-blue-500/5 border border-dashed border-blue-500/20 rounded-xl flex items-center justify-between group">
                    <div class="flex items-center gap-4">
                        <div class="p-2 bg-blue-500/10 rounded-lg text-blue-500"><Database size={18} /></div>
                        <div>
                            <h4 class="text-xs font-semibold text-text-primary">Post-execution state</h4>
                            <p class="text-[10px] text-text-secondary opacity-70">The database index has been synchronized with the results of this job.</p>
                        </div>
                    </div>
                    <Button variant="outline" size="sm" class="h-8 px-4 text-[10px] border-blue-500/30 text-blue-400 group-hover:bg-blue-500/10 transition-all" href={job.job_type === 'SCAN' ? '/filesystem' : '/inventory'}>
                        View changes <ArrowRight size={14} class="ml-2" />
                    </Button>
                </div>
            </div>

            <footer class="p-6 bg-bg-tertiary/20 border-t border-border-color flex justify-end">
                <Button variant="secondary" class="h-10 px-6 font-medium text-sm" onclick={onClear}>Close detail view</Button>
            </footer>
        {/if}
    </Card>
</Dialog>
