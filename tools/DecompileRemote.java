// Export provisional pseudocode from a stock WoRWS OTA member without executing it.
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.io.PrintWriter;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;

public class DecompileRemote extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Path output = Path.of(args[0]);
        Address base = currentProgram.getMinAddress();
        boolean arm = currentProgram.getLanguageID().getIdAsString().startsWith("ARM:");
        if (arm) {
            currentProgram.getProgramContext().setValue(currentProgram.getRegister("TMode"),
                base, currentProgram.getMaxAddress(), BigInteger.ONE);
            for (long offset : new long[] {0, 0xc, 0x22}) {
                seedFunction(base.add(offset), false);
            }
        }

        byte[] image = new byte[(int) currentProgram.getMemory().getSize()];
        currentProgram.getMemory().getBytes(base, image);
        for (int offset = 0; offset < image.length - 4 && !monitor.isCancelled(); offset += arm ? 2 : 1) {
            int first = Byte.toUnsignedInt(image[offset]);
            int second = Byte.toUnsignedInt(image[offset + 1]);
            int third = Byte.toUnsignedInt(image[offset + 2]);
            if (arm && (second == 0xb5 || (first == 0x2d && second == 0xe9
                    && (image[offset + 3] & 0x40) != 0))) {
                seedFunction(base.add(offset), false);
            }
            if (!arm && first == 0x36 && (second & 0x1f) == 1 && third == 0) {
                seedFunction(base.add(offset), true);
            }
        }
        analyzeAll(currentProgram);

        Files.createDirectories(output);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int total = 0;
        int completed = 0;
        try (PrintWriter index = new PrintWriter(Files.newBufferedWriter(output.resolve("functions.tsv")));
             PrintWriter source = new PrintWriter(Files.newBufferedWriter(output.resolve("pseudocode.c")))) {
            index.println("address\tname\tbytes\tdecompiled");
            source.println("/* Provisional Ghidra output. Function boundaries and names need verification. */");
            for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
                if (function.isExternal() || monitor.isCancelled()) {
                    continue;
                }
                total++;
                DecompileResults result = decompiler.decompileFunction(function, 5, monitor);
                boolean ok = result.decompileCompleted() && result.getDecompiledFunction() != null;
                index.printf("%s\t%s\t%d\t%s%n", function.getEntryPoint(), function.getName(),
                    function.getBody().getNumAddresses(), ok);
                if (ok) {
                    completed++;
                    source.printf("\n/* %s */\n%s%n", function.getEntryPoint(),
                        result.getDecompiledFunction().getC());
                }
            }
        } finally {
            decompiler.dispose();
        }
        println("REMOTE_ANALYSIS functions=" + total + " decompiled=" + completed);
    }

    private void seedFunction(Address entry, boolean xtensa) throws Exception {
        if (getFunctionContaining(entry) != null || getInstructionContaining(entry) != null) {
            return;
        }
        if (xtensa) {
            Instruction instruction = getInstructionAt(entry);
            if (instruction == null) {
                disassemble(entry);
                instruction = getInstructionAt(entry);
            }
            if (instruction == null || !instruction.getMnemonicString().equalsIgnoreCase("entry")) {
                return;
            }
        } else {
            disassemble(entry);
        }
        if (getInstructionAt(entry) != null) {
            createFunction(entry, null);
        }
    }
}
