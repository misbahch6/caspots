#heuristic dnf(I,J) : before(I,J). [2@2,false] % for diversity
#heuristic dnf(I,J). [1,false]     % for subset minimal solution 
#external before(I,J)  : dnf(I,J). % for diversity

#program skip.
:- dnf(I,J) : (I,J) = @dnf(); not dnf(I,J) : (I,J) = @ndnf().
