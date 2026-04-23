<script lang="ts">
    import { Plus, CassetteTape, HardDrive, Cloud, MapPin, Edit3, Scissors } from 'lucide-svelte';

    // Mock Data
    const mediaList = [
        { id: 1, type: 'LTO-6', identifier: 'BUP-00001', capacity: 2500, used: 2450, status: 'Full', location: 'Bank Vault' },
        { id: 2, type: 'LTO-6', identifier: 'BUP-00002', capacity: 2500, used: 1200, status: 'Active', location: 'In Drive' },
        { id: 3, type: 'HDD', identifier: 'HDD-001', capacity: 8000, used: 4000, status: 'Active', location: 'Shelf 2' },
        { id: 4, type: 'Cloud', identifier: 's3://my-backups', capacity: Infinity, used: 1500, status: 'Active', location: 'AWS-East' }
    ];

    function getPercentage(used: number, capacity: number) {
        if (capacity === Infinity) return 0;
        return Math.min(100, Math.round((used / capacity) * 100));
    }
</script>

<svelte:head>
    <title>Inventory - TapeHoard</title>
</svelte:head>

<div class="flex justify-between items-center mb-8 bg-bg-secondary p-6 rounded-lg border border-border-color shadow-lg">
    <div>
        <h1 class="text-3xl font-bold tracking-tight text-text-primary">Global Inventory</h1>
        <p class="text-text-secondary mt-1">Manage physical and cloud storage media across all locations.</p>
    </div>
    <button class="btn btn-primary h-11 px-8"><Plus size={18} class="mr-2" /> Register New Media</button>
</div>

<div class="card stats-summary">
    <h3>Storage Pool Summary</h3>
    <div class="stats-grid">
        <div class="stat-box">
            <span class="label">Total Media</span>
            <span class="value">{mediaList.length}</span>
        </div>
        <div class="stat-box">
            <span class="label">Total Capacity</span>
            <span class="value">13.0 TB</span>
        </div>
        <div class="stat-box">
            <span class="label">Total Used</span>
            <span class="value">9.1 TB</span>
        </div>
        <div class="stat-box">
            <span class="label">Utilization</span>
            <span class="value">70%</span>
        </div>
    </div>
</div>

<div class="card no-padding">
    <table class="data-table">
        <thead>
            <tr>
                <th>Identifier</th>
                <th>Type</th>
                <th>Capacity Used</th>
                <th>Status</th>
                <th>Location</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {#each mediaList as media}
                <tr>
                    <td><span class="mono"><strong>{media.identifier}</strong></span></td>
                    <td>
                        {#if media.type.startsWith('LTO')}
                            <span class="badge badge-tape"><CassetteTape size={12} style="margin-right: 4px;" /> {media.type}</span>
                        {:else if media.type === 'HDD'}
                            <span class="badge badge-hdd"><HardDrive size={12} style="margin-right: 4px;" /> {media.type}</span>
                        {:else}
                            <span class="badge badge-cloud"><Cloud size={12} style="margin-right: 4px;" /> {media.type}</span>
                        {/if}
                    </td>
                    <td>
                        <div class="progress-info">
                            <div class="progress-container">
                                <div class="progress-bar" style="width: {getPercentage(media.used, media.capacity)}%; background-color: {media.status === 'Full' ? 'var(--color-error-color)' : 'var(--color-action-color)'}"></div>
                            </div>
                            <span class="mono">{media.used} GB / {media.capacity === Infinity ? '∞' : media.capacity + ' GB'}</span>
                        </div>
                    </td>
                    <td>
                        <div class="status-cell">
                            <span class="status-dot" class:active={media.status === 'Active'} class:full={media.status === 'Full'}></span>
                            {media.status}
                        </div>
                    </td>
                    <td>
                        <div class="location-cell">
                            <MapPin size={14} color="var(--color-text-secondary)" />
                            {media.location}
                        </div>
                    </td>
                    <td>
                        <div class="actions">
                            <button class="btn btn-secondary btn-icon-only" title="Edit"><Edit3 size={14} /></button>
                            {#if media.status === 'Full' && media.type.startsWith('LTO')}
                                <button class="btn btn-warning btn-icon-only" title="Groom Tape"><Scissors size={14} /></button>
                            {/if}
                        </div>
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>

<style>
    .no-padding {
        padding: 0;
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: var(--spacing-lg);
        margin-top: var(--spacing-md);
    }

    .stat-box .label {
        color: var(--color-text-secondary);
        font-size: 0.8rem;
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.05em;
    }

    .stat-box .value {
        display: block;
        font-size: 1.75rem;
        font-weight: 700;
        color: var(--color-text-primary);
        margin-top: 0.25rem;
    }

    .progress-info {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .progress-info span {
        font-size: 0.75rem;
        color: var(--color-text-secondary);
    }

    .badge-tape { background-color: rgba(52, 152, 219, 0.15); color: #3498db; }
    .badge-hdd { background-color: rgba(241, 196, 15, 0.15); color: #f1c40f; }
    .badge-cloud { background-color: rgba(46, 204, 113, 0.15); color: #2ecc71; }

    .status-cell {
        display: flex;
        align-items: center;
        gap: var(--spacing-sm);
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: var(--color-text-secondary);
    }

    .status-dot.active { background-color: var(--color-success-color); box-shadow: 0 0 8px var(--color-success-color); }
    .status-dot.full { background-color: var(--color-error-color); }

    .location-cell {
        display: flex;
        align-items: center;
        gap: var(--spacing-xs);
        color: var(--color-text-secondary);
    }

    .actions {
        display: flex;
        gap: var(--spacing-xs);
    }

    .btn-icon-only {
        padding: 0.4rem;
    }

    .btn-warning {
        background-color: rgba(243, 156, 18, 0.2);
        color: #f39c12;
        border: 1px solid rgba(243, 156, 18, 0.3);
    }
</style>
