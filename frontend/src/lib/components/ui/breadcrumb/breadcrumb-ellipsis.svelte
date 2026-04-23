<script lang="ts">
	import type { HTMLAttributes } from "svelte/elements";
	import { MoreHorizontal } from "lucide-svelte";
	import { cn } from "$lib/utils";

	let { class: className, ...rest }: HTMLAttributes<HTMLSpanElement> = $props();
</script>

<span
	role="presentation"
	aria-hidden="true"
	class={cn("flex h-9 w-9 items-center justify-center", className)}
	{...rest}
>
	<MoreHorizontal class="h-4 w-4" />
	<span class="sr-only">More</span>
</span>
