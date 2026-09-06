using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security;
using System.Text;

public sealed class BackupManager
{
    private static readonly HashSet<string> ExcludedDirectories =
        new HashSet<string>(
            new[] { ".git", ".vs", "bin", "obj", "node_modules", "dist", "build", "packages" },
            StringComparer.OrdinalIgnoreCase);

    private readonly string sourceRoot;
    private readonly string destinationRoot;
    private readonly List<string> errors = new List<string>();
    private int copiedCount;
    private int skippedCount;
    private int excludedDirectoryCount;
    private int prunedDirectoryCount;
    private DateTime startedUtc;
    private DateTime finishedUtc;
    private string logPath;

    public BackupManager(string sourcePath, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
            throw new ArgumentException("La ruta de origen es obligatoria.", "sourcePath");
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("La ruta de destino es obligatoria.", "destinationPath");

        sourceRoot = NormalizeRoot(sourcePath);
        destinationRoot = NormalizeRoot(destinationPath);
    }

    public void CreateBackup()
    {
        startedUtc = DateTime.UtcNow;
        if (!Directory.Exists(sourceRoot))
            throw new DirectoryNotFoundException("No existe el origen: " + sourceRoot);

        Directory.CreateDirectory(destinationRoot);
        logPath = Path.Combine(
            destinationRoot,
            "backup-" + DateTime.Now.ToString("yyyyMMdd-HHmmss", CultureInfo.InvariantCulture) + ".log");

        Exception criticalError = null;
        try
        {
            PruneExcludedDirectories(destinationRoot);
            CopyDirectory(sourceRoot);
        }
        catch (Exception error)
        {
            criticalError = error;
            errors.Add("CRÍTICO | " + FormatError(error));
        }
        finally
        {
            finishedUtc = DateTime.UtcNow;
            WriteLog();
        }

        if (criticalError != null)
            throw new InvalidOperationException("El respaldo terminó con un error crítico.", criticalError);
    }

    private void CopyDirectory(string currentDirectory)
    {
        string[] files;
        try
        {
            files = Directory.GetFiles(currentDirectory);
        }
        catch (UnauthorizedAccessException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (IOException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (SecurityException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }

        foreach (string sourceFile in files)
            CopyFile(sourceFile);

        string[] directories;
        try
        {
            directories = Directory.GetDirectories(currentDirectory);
        }
        catch (UnauthorizedAccessException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (IOException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (SecurityException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }

        foreach (string directory in directories)
        {
            string name = Path.GetFileName(directory);
            if (ExcludedDirectories.Contains(name) || IsSameOrChild(directory, destinationRoot))
            {
                excludedDirectoryCount++;
                continue;
            }
            CopyDirectory(directory);
        }
    }

    private void PruneExcludedDirectories(string currentDirectory)
    {
        string[] directories;
        try
        {
            directories = Directory.GetDirectories(currentDirectory);
        }
        catch (UnauthorizedAccessException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (IOException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }
        catch (SecurityException error)
        {
            RecordDirectoryError(currentDirectory, error);
            return;
        }

        foreach (string directory in directories)
        {
            if (ExcludedDirectories.Contains(Path.GetFileName(directory)))
            {
                try
                {
                    Directory.Delete(directory, true);
                    prunedDirectoryCount++;
                }
                catch (UnauthorizedAccessException error)
                {
                    RecordDirectoryError(directory, error);
                }
                catch (IOException error)
                {
                    RecordDirectoryError(directory, error);
                }
                catch (SecurityException error)
                {
                    RecordDirectoryError(directory, error);
                }
                continue;
            }
            PruneExcludedDirectories(directory);
        }
    }

    private void CopyFile(string sourceFile)
    {
        string relativePath = GetRelativePath(sourceRoot, sourceFile);
        string destinationFile = Path.Combine(destinationRoot, relativePath);
        try
        {
            DateTime sourceTimestamp = File.GetLastWriteTimeUtc(sourceFile);
            if (File.Exists(destinationFile) &&
                sourceTimestamp <= File.GetLastWriteTimeUtc(destinationFile))
            {
                skippedCount++;
                return;
            }

            string destinationDirectory = Path.GetDirectoryName(destinationFile);
            if (!string.IsNullOrEmpty(destinationDirectory))
                Directory.CreateDirectory(destinationDirectory);
            File.Copy(sourceFile, destinationFile, true);
            File.SetLastWriteTimeUtc(destinationFile, sourceTimestamp);
            copiedCount++;
        }
        catch (UnauthorizedAccessException error)
        {
            RecordFileError(relativePath, error);
        }
        catch (IOException error)
        {
            RecordFileError(relativePath, error);
        }
        catch (SecurityException error)
        {
            RecordFileError(relativePath, error);
        }
        catch (NotSupportedException error)
        {
            RecordFileError(relativePath, error);
        }
    }

    private void RecordDirectoryError(string directory, Exception error)
    {
        errors.Add("DIRECTORIO | " + GetRelativePath(sourceRoot, directory) + " | " + FormatError(error));
    }

    private void RecordFileError(string relativePath, Exception error)
    {
        errors.Add("ARCHIVO | " + relativePath + " | " + FormatError(error));
    }

    private void WriteLog()
    {
        var log = new StringBuilder();
        log.AppendLine("RESPALDO INCREMENTAL DEL PROYECTO");
        log.AppendLine("Inicio UTC: " + startedUtc.ToString("O", CultureInfo.InvariantCulture));
        log.AppendLine("Fin UTC: " + finishedUtc.ToString("O", CultureInfo.InvariantCulture));
        log.AppendLine("Origen: " + sourceRoot);
        log.AppendLine("Destino: " + destinationRoot);
        log.AppendLine("Archivos copiados: " + copiedCount);
        log.AppendLine("Archivos omitidos/no actualizados: " + skippedCount);
        log.AppendLine("Directorios excluidos: " + excludedDirectoryCount);
        log.AppendLine("Directorios excluidos depurados del destino: " + prunedDirectoryCount);
        log.AppendLine("Errores: " + errors.Count);
        if (errors.Count > 0)
        {
            log.AppendLine();
            log.AppendLine("DETALLE DE ERRORES");
            foreach (string error in errors)
                log.AppendLine(error);
        }
        File.WriteAllText(logPath, log.ToString(), new UTF8Encoding(false));

        Console.WriteLine("Respaldo completado.");
        Console.WriteLine("Copiados: {0}; omitidos: {1}; errores: {2}", copiedCount, skippedCount, errors.Count);
        Console.WriteLine("Log: " + logPath);
    }

    private static string NormalizeRoot(string path)
    {
        return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static bool IsSameOrChild(string candidatePath, string parentPath)
    {
        string candidate = NormalizeRoot(candidatePath);
        return candidate.Equals(parentPath, StringComparison.OrdinalIgnoreCase) ||
            candidate.StartsWith(parentPath + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    private static string GetRelativePath(string root, string path)
    {
        string normalizedPath = Path.GetFullPath(path);
        if (normalizedPath.Equals(root, StringComparison.OrdinalIgnoreCase))
            return ".";
        return normalizedPath.Substring(root.Length)
            .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static string FormatError(Exception error)
    {
        return error.GetType().Name + ": " + error.Message;
    }
}

internal static class Program
{
    private const string DefaultSource = @"C:\Users\gbzk\Downloads\Games\Games\real_vs_ia";
    private const string DefaultDestination = @"C:\Users\gbzk\Downloads\respaldo game";

    private static int Main(string[] args)
    {
        string source = args.Length > 0 ? args[0] : DefaultSource;
        string destination = args.Length > 1 ? args[1] : DefaultDestination;
        try
        {
            new BackupManager(source, destination).CreateBackup();
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("ERROR CRÍTICO: " + error);
            return 1;
        }
    }
}
