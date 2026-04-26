<script lang="ts">
    import { onMount } from 'svelte';

    let { items = [] } = $props<{
        items: { label: string; value: number; color?: string; fullPath?: string; children?: any[] }[];
    }>();

    let container: HTMLElement;
    let containerWidth = $state(100);
    let containerHeight = $state(100);

    onMount(() => {
        const resizeObserver = new ResizeObserver((entries) => {
            for (let entry of entries) {
                containerWidth = entry.contentRect.width;
                containerHeight = entry.contentRect.height;
            }
        });
        if (container) {
            resizeObserver.observe(container);
        }
        return () => resizeObserver.disconnect();
    });

    const colors = [
        'bg-blue-600', 'bg-purple-600', 'bg-orange-600',
        'bg-emerald-600', 'bg-rose-600', 'bg-cyan-600',
        'bg-amber-600', 'bg-fuchsia-600', 'bg-teal-600', 'bg-indigo-600'
    ];

    function computeRects(nodeItems: any[], width: number, height: number, availableColors: string[]) {
        if (!nodeItems || nodeItems.length === 0 || width <= 0 || height <= 0) return [];

        let total = nodeItems.reduce((s: number, i: any) => s + i.value, 0);
        if (total <= 0) return [];

        let result = [];
        let x = 0;
        let y = 0;
        let w = width;
        let h = height;

        for (let i = 0; i < nodeItems.length; i++) {
            const item = nodeItems[i];
            let ratio = item.value / total;

            let rectW, rectH;
            if (w > h) {
                // Vertical slice
                rectW = w * ratio;
                rectH = h;
                result.push({ x, y, w: rectW, h: rectH, item, color: item.color || availableColors[i % availableColors.length] });
                x += rectW;
                w -= rectW;
            } else {
                // Horizontal slice
                rectW = w;
                rectH = h * ratio;
                result.push({ x, y, w: rectW, h: rectH, item, color: item.color || availableColors[i % availableColors.length] });
                y += rectH;
                h -= rectH;
            }
            total -= item.value;
        }
        return result;
    }

    const rects = $derived(computeRects(items, containerWidth, containerHeight, colors));

    function formatSize(bytes: number) {
        if (!bytes || bytes === 0) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB", "PB"];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }
</script>

{#snippet treeNode(item: any, x: number, y: number, w: number, h: number, depth: number, color: string)}
    <div
        class={`absolute flex flex-col transition-all group overflow-hidden ${depth === 0 ? color + ' border border-bg-secondary rounded-sm' : 'bg-black/20 border border-white/5 hover:bg-black/10'}`}
        style={`left: ${x}px; top: ${y}px; width: ${w}px; height: ${h}px;`}
        title={`${item.fullPath || item.label}: ${formatSize(item.value)}`}
    >
        {#if w > 40 && h > 16}
            <div class={`px-1 py-0.5 shrink-0 ${depth === 0 ? 'bg-black/10' : ''}`}>
                <span class={`font-black uppercase tracking-widest truncate w-full block text-[9px] drop-shadow-md ${depth === 0 ? 'text-white/90' : 'text-white/50'}`}>
                    {item.label}
                </span>
            </div>
        {/if}

        {#if item.children && item.children.length > 0 && w > 30 && h > 30}
            <!-- Sub-container for children, giving space for the label -->
            <div class="relative flex-1 w-full overflow-hidden">
                {#each computeRects(item.children, w, h - (w > 40 && h > 16 ? 18 : 0), [color]) as childRect}
                    {@render treeNode(childRect.item, childRect.x, childRect.y, childRect.w, childRect.h, depth + 1, color)}
                {/each}
            </div>
        {:else if w > 50 && h > 30 && (!item.children || item.children.length === 0)}
            <div class="flex-1 flex items-center justify-center p-1">
                <span class="text-white/80 font-bold mono text-[8px] sm:text-[9px] truncate w-full text-center drop-shadow-md">
                    {formatSize(item.value)}
                </span>
            </div>
        {/if}
    </div>
{/snippet}

<div bind:this={container} class="w-full min-h-[300px] flex-1 relative overflow-hidden rounded-xl bg-bg-primary border border-border-color/30">
    {#each rects as rect}
        {@render treeNode(rect.item, rect.x, rect.y, rect.w, rect.h, 0, rect.color)}
    {/each}
</div>
