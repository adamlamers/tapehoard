<script lang="ts">
        import {
                Folder,
                File,
                FileText,
                Film,
                Image,
                Archive,
                Link as LinkIcon,
                MoreVertical,
                ExternalLink,
                CassetteTape,
                ShieldCheck,
                ShieldAlert,
                Square,
                EyeOff
        } from "lucide-svelte";
        import { Checkbox } from "$lib/components/ui/checkbox";
        import { Button } from "$lib/components/ui/button";
        import type { FileItem } from "$lib/types";
        import { cn } from "$lib/utils";

        let {
                item,
                isSelected = false,
                onClick = (e: MouseEvent) => {},
                onDoubleClick = () => {},
                onToggleTrack = () => {},
                mode = "host",
                colWidths = { mtime: 200, type: 150, size: 120 }
        } = $props<{
                item: FileItem;
                isSelected?: boolean;
                onClick?: (e: MouseEvent) => void;
                onDoubleClick?: () => void;
                onToggleTrack?: () => void;
                mode?: "host" | "index";
                colWidths?: { mtime: number; type: number; size: number };
        }>();

        const FileIcon = $derived.by(() => {
                if (item.type === "directory") return Folder;
                if (item.type === "link") return LinkIcon;

                const ext = item.name.split(".").pop()?.toLowerCase();
                switch (ext) {
                        case "txt":
                        case "pdf":
                        case "doc":
                        case "docx":
                                return FileText;
                        case "mp4":
                        case "mkv":
                        case "mov":
                        case "avi":
                                return Film;
                        case "jpg":
                        case "jpeg":
                        case "png":
                        case "gif":
                        case "webp":
                                return Image;
                        case "zip":
                        case "rar":
                        case "7z":
                        case "tar":
                        case "gz":
                                return Archive;
                        default:
                                return File;
                }
        });

        function formatSize(bytes?: number) {
                if (bytes === undefined) return "--";
                if (bytes === 0) return "0 B";
                const units = ["B", "KB", "MB", "GB", "TB"];
                let unitIndex = 0;
                let size = bytes;
                while (size >= 1024 && unitIndex < units.length - 1) {
                        size /= 1024;
                        unitIndex++;
                }
                return `${size.toFixed(1)} ${units[unitIndex]}`;
        }

        function formatDate(mtime?: number) {
                if (!mtime) return "--";
                const date = new Date(mtime * 1000);
                return date.toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit"
                });
        }

        function getItemTypeLabel(item: FileItem) {
                if (item.type === "directory") return "File folder";
                if (item.type === "link") return "System link";
                const ext = item.name.split(".").pop()?.toUpperCase();
                return ext ? `${ext} File` : "File";
        }
</script>

<div
        class={cn(
                "group flex h-10 items-center border-b border-border-color/10 transition-all cursor-pointer select-none",
                isSelected
                        ? "bg-blue-500/15 border-l-2 border-l-blue-500"
                        : "hover:bg-white/5 border-l-2 border-l-transparent",
                item.ignored && "opacity-40 grayscale-[0.5]",
                (mode === 'index' && item.type === 'file' && item.vulnerable) && "opacity-60 cursor-not-allowed"
        )}
        role="button"
        tabindex="0"
        onclick={onClick}
        ondblclick={onDoubleClick}
        onkeydown={(e) => e.key === "Enter" && onDoubleClick()}
>
        <!-- TRACKING STATUS / SELECTION -->
        <div
                class="flex h-10 w-12 shrink-0 items-center justify-center border-r border-border-color/10"
                onclick={(e) => {
                        e.stopPropagation();
                        if (item.ignored) return;
                        if (mode === 'index' && item.type === 'file' && item.vulnerable) return;
                        onToggleTrack();
                }}
                onkeydown={(e) => e.key === " " && e.stopPropagation()}
                role="none"
        >
                {#if item.ignored}
                        <div class="text-text-secondary/40">
                                <EyeOff size={16} />
                        </div>
                {:else if mode === 'host'}
                        {#if item.tracked}
                                <div class="text-success-color bg-success-color/10 p-1 rounded-md">
                                        <ShieldCheck size={16} />
                                </div>
                        {:else}
                                <div class="text-text-secondary/20 group-hover:text-text-secondary/40 p-1">
                                        <Square size={16} />
                                </div>
                        {/if}
                {:else}
                        <Checkbox
                                checked={item.selected}
                                indeterminate={item.indeterminate}
                                onCheckedChange={onToggleTrack}
                                disabled={item.type === 'file' && item.vulnerable}
                        />
                {/if}
        </div>

        <!-- NAME & ICON -->
        <div class="flex flex-auto min-w-[200px] items-center gap-3 px-4 h-full border-r border-border-color/10 overflow-hidden">
                <div class="shrink-0 relative">
                        <FileIcon
                                size={18}
                                class={cn(
                                        item.type === "directory" ? "text-yellow-500/80 fill-yellow-500/10" : "text-text-secondary",
                                        item.ignored && "text-text-secondary/40"
                                )}
                        ></FileIcon>
                        {#if item.type === "link"}
                                <div
                                        class="absolute -bottom-1 -right-1 bg-bg-secondary rounded-full p-0.5 border border-border-color"
                                >
                                        <ExternalLink size={8} class="text-action-color" />
                                </div>
                        {/if}
                </div>

                <div class="flex flex-col min-w-0">
                        <div class="flex items-center gap-2">
                                <span
                                        class={cn(
                                                "truncate text-[13px] transition-colors",
                                                !item.ignored && item.tracked
                                                        ? "text-success-color font-bold"
                                                        : isSelected
                                                                ? "text-text-primary font-medium"
                                                                : "text-text-secondary group-hover:text-text-primary",
                                                item.ignored && "line-through decoration-text-secondary/40"
                                        )}
                                >
                                        {item.name}
                                </span>
                                {#if mode === "index"}
                                        {#if item.media && item.media.length > 0}
                                                <div class="flex gap-1 overflow-hidden shrink-0">
                                                        {#each item.media as m}
                                                                <span class="inline-flex items-center gap-1 bg-blue-500/10 text-blue-400 text-[9px] px-1.5 py-0.5 rounded border border-blue-500/20 font-bold uppercase tracking-wider">
                                                                        <CassetteTape size={10} />
                                                                        {m}
                                                                </span>
                                                        {/each}
                                                </div>
                                        {:else if item.vulnerable}
                                                <span class="inline-flex items-center gap-1 bg-error-color/10 text-error-color text-[8px] px-1.5 py-0.5 rounded border border-error-color/20 font-black uppercase tracking-widest">
                                                        <ShieldAlert size={10} />
                                                        Vulnerable
                                                </span>
                                        {:else if item.type === 'directory'}
                                                <span class="inline-flex items-center gap-1 bg-success-color/10 text-success-color text-[8px] px-1.5 py-0.5 rounded border border-success-color/20 font-black uppercase tracking-widest">
                                                        <ShieldCheck size={10} />
                                                        Protected
                                                </span>
                                        {:else if item.type === 'file'}
                                                <span class="inline-flex items-center gap-1 bg-error-color/10 text-error-color text-[8px] px-1.5 py-0.5 rounded border border-error-color/20 font-black uppercase tracking-widest">
                                                        <ShieldAlert size={10} />
                                                        Vulnerable
                                                </span>
                                        {/if}
                                {/if}
                        </div>
                </div>
        </div>

        <!-- DATE MODIFIED -->
        <div
                class="shrink-0 px-4 h-full flex items-center text-[12px] text-text-secondary tabular-nums font-medium border-r border-border-color/10"
                style="width: {colWidths.mtime}px"
        >
                {formatDate(item.mtime)}
        </div>

        <!-- TYPE -->
        <div
                class="shrink-0 px-4 h-full flex items-center text-[12px] text-text-secondary truncate font-medium border-r border-border-color/10"
                style="width: {colWidths.type}px"
        >
                {getItemTypeLabel(item)}
        </div>

        <!-- SIZE -->
        <div
                class="shrink-0 px-4 h-full flex items-center justify-end text-[12px] text-text-secondary mono text-right tabular-nums font-medium border-r border-border-color/10"
                style="width: {colWidths.size}px"
        >
                {item.type === "directory" ? "" : formatSize(item.size)}
        </div>

        <!-- QUICK ACTIONS -->
        <div class="w-10 shrink-0 flex justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                <Button
                        variant="ghost"
                        size="icon"
                        class="h-7 w-7 text-text-secondary hover:text-text-primary hover:bg-white/10"
                >
                        <MoreVertical size={14} />
                </Button>
        </div>
</div>
