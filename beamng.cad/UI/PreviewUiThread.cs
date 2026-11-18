using System;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace BeamNG.Cad.UI
{
    internal static class PreviewUiThread
    {
        // COM hosts and automation callers need not install a WinForms context.
        // Establish one at the window boundary so every asynchronous graphics
        // continuation returns to the same owning UI thread.
        internal static Task<T> Run<T>(Control owner,Func<Task<T>> action)
        {
            var result=new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
            if(owner.IsDisposed){result.SetCanceled();return result.Task;}
            EventHandler disposed=null;
            disposed=(s,e)=>{result.TrySetCanceled();owner.Disposed-=disposed;};
            owner.Disposed+=disposed;
            try {owner.BeginInvoke(new Action(()=>{
                var previous=SynchronizationContext.Current;
                Task<T> operation;
                try
                {
                    SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
                    operation=action();
                }
                catch(Exception error){result.TrySetException(error);owner.Disposed-=disposed;return;}
                finally{SynchronizationContext.SetSynchronizationContext(previous);}
                Complete(operation,result,owner,disposed);
            }));}
            catch(InvalidOperationException){owner.Disposed-=disposed;result.TrySetCanceled();}
            return result.Task;
        }
        private static async void Complete<T>(Task<T> operation,TaskCompletionSource<T> result,Control owner,EventHandler disposed)
        {
            try{result.TrySetResult(await operation.ConfigureAwait(false));}
            catch(OperationCanceledException){result.TrySetCanceled();}
            catch(Exception error){result.TrySetException(error);}
            finally{owner.Disposed-=disposed;}
        }
    }
}
